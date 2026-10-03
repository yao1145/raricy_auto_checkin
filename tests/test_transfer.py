import copy
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests

from backend import transfer


CONFIG = {"site": {"checkin_url": "https://raricy.com/checkin"}, "accounts": [
    {"username": "alice", "password": "pw"},
    {"username": "recipient", "password": "pw"},
    {"username": "disabled", "password": "pw", "enabled": False},
]}
SETTINGS = {"recipient": "recipient", "amount": "3.125", "accounts": ["all"]}


class TransferTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path_patch = mock.patch.object(transfer, "TRANSFER_DB_PATH", Path(self.tmp.name) / "transfer.db")
        self.path_patch.start()
        self.session = mock.Mock(raricy_username="alice", raricy_user_id="alice-id")
        self.session.post.return_value = mock.Mock(status_code=200)
        self.session.post.return_value.json.return_value = {
            "code": 200, "amount": 3.125, "balance": 6.875, "transfer_id": "receipt", "message": "成功"}
        self.login_patch = mock.patch.object(transfer, "login", return_value=self.session)
        self.login = self.login_patch.start()

    def tearDown(self):
        self.login_patch.stop()
        self.path_patch.stop()
        self.tmp.cleanup()

    def test_excludes_self_and_disabled_and_records_receipt(self):
        results = transfer.run_batch(CONFIG, SETTINGS, "batch", "manual")
        self.assertEqual(len(results), 2)
        self.assertEqual([r["status"] for r in results], ["success", "skipped"])
        self.login.assert_called_once_with(CONFIG, "alice", "pw")
        payload = self.session.post.call_args.kwargs["json"]
        self.assertEqual(payload["to_username"], "recipient")
        self.assertEqual(payload["amount"], "3.125")
        self.assertLessEqual(len(payload["idempotency_key"]), 48)
        self.assertEqual(transfer.read_history()[0]["transfer_id"], "receipt")
        self.session.close.assert_called_once()

    def test_email_alias_of_recipient_is_skipped_after_login(self):
        self.session.raricy_username = "recipient"
        results = transfer.run_batch(CONFIG, SETTINGS, "batch", "manual")
        self.assertTrue(all(r["status"] == "skipped" for r in results))
        self.session.post.assert_not_called()

    def test_retry_uses_same_key_and_replayed_batch_does_not_send_again(self):
        good = self.session.post.return_value
        self.session.post.side_effect = [requests.Timeout(), good]
        transfer.run_batch(CONFIG, SETTINGS, "batch", "manual")
        calls = self.session.post.call_args_list
        self.assertEqual(calls[0].kwargs["json"], calls[1].kwargs["json"])
        transfer.run_batch(CONFIG, SETTINGS, "batch", "manual")
        self.assertEqual(self.session.post.call_count, 2)

    def test_failure_does_not_stop_other_accounts(self):
        config = copy.deepcopy(CONFIG)
        config["accounts"].append({"username": "bob", "password": "pw"})
        self.login.side_effect = [ValueError("bad login"), self.session]
        results = transfer.run_batch(config, SETTINGS, "batch", "manual")
        self.assertEqual([r["status"] for r in results], ["failed", "skipped", "success"])

    def test_amount_validation(self):
        for amount in (0, -1, True, "NaN", "Infinity", "0.00001", "3.12345", [], None, "1e400", "3.00000000000000000000000000001"):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                transfer.validate_settings({**SETTINGS, "amount": amount})
        self.assertEqual(transfer.validate_settings({**SETTINGS, "amount": "0.0001"})["amount"], "0.0001")

    def test_selection_and_empty_list(self):
        results = transfer.run_batch(CONFIG, {**SETTINGS, "accounts": ["recipient"]}, "batch", "manual")
        self.assertEqual(results[0]["status"], "skipped")
        self.login.assert_not_called()
        with self.assertRaises(ValueError):
            transfer.validate_settings({**SETTINGS, "accounts": []})

    def test_ambiguous_network_result_is_marked_unknown(self):
        self.session.post.side_effect = requests.Timeout()
        result = transfer.run_batch(CONFIG, SETTINGS, "batch", "manual")[0]
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(transfer.read_history()[0]["status"], "unknown")

    def test_reusing_batch_with_changed_parameters_preserves_original_receipt(self):
        transfer.run_batch(CONFIG, SETTINGS, "batch", "manual")
        with self.assertRaises(ValueError):
            transfer.run_batch(CONFIG, {**SETTINGS, "amount": "4"}, "batch", "manual")
        self.assertEqual(transfer.read_history()[0]["amount"], "3.125")
        self.assertEqual(transfer.read_history()[0]["status"], "success")
        transfer.run_batch(CONFIG, SETTINGS, "batch", "manual")
        self.assertEqual(self.session.post.call_count, 1)

    def test_retry_all_does_not_add_new_accounts_to_existing_batch(self):
        transfer.run_batch(CONFIG, SETTINGS, "batch", "manual")
        config = copy.deepcopy(CONFIG)
        config["accounts"].append({"username": "bob", "password": "pw"})
        transfer.run_batch(config, SETTINGS, "batch", "manual")
        self.assertNotIn('bob', [call.args[1] for call in self.login.call_args_list])

    def test_insufficient_balance_does_not_retry(self):
        self.session.post.return_value.status_code = 400
        self.session.post.return_value.json.return_value = {"code": 400, "message": "余额不足"}
        result = transfer.run_batch(CONFIG, SETTINGS, "batch", "manual")[0]
        self.assertEqual(result["message"], "余额不足")
        self.assertEqual(self.session.post.call_count, 1)

    def test_duplicate_aliases_only_transfer_once(self):
        config = copy.deepcopy(CONFIG)
        config["accounts"].append({"username": "alias@example.com", "password": "pw"})
        results = transfer.run_batch(config, SETTINGS, "batch", "manual")
        self.assertEqual([r["status"] for r in results], ["success", "skipped", "skipped"])
        self.assertEqual(self.session.post.call_count, 1)


if __name__ == "__main__":
    unittest.main()
