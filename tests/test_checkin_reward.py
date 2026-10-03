import unittest
from unittest import mock
from backend.checkin import CheckinEngine
from backend import client


class RewardTest(unittest.TestCase):
    def test_login_verification_uses_balance_for_regular_transfer_accounts(self):
        session = mock.Mock()
        session.get.return_value.status_code = 200
        session.get.return_value.json.return_value = {"code": 200, "balance": 10}
        self.assertTrue(client._verify_login(session, {"site": {"checkin_url": "https://raricy.com/checkin"}}))
        self.assertEqual(session.get.call_args.args[0], "https://raricy.com/api/fish/balance")

    def test_fixed_reward_requires_no_claim_request_even_with_old_flags(self):
        with mock.patch("backend.checkin.load_config", return_value={"fortune": {"enabled": True}}):
            engine = CheckinEngine()
        session = mock.Mock()
        session.post.return_value.json.return_value = {
            "code": 200, "reward_fish": 3, "today_fish": 3, "dried_fish": 10,
            "show_fortune": True, "fortune_pending": True}
        with mock.patch.object(engine, "_login", return_value=session), \
                mock.patch("backend.checkin.api_url", return_value="https://raricy.com/api/checkin"):
            result = engine.execute("u", "p")
        self.assertTrue(result["success"])
        self.assertEqual(result["reward_fish"], 3)
        self.assertEqual(result["fortune"]["result_value"], "3")
        self.assertEqual(session.post.call_count, 1)

    def test_already_checked_reports_actual_reward(self):
        with mock.patch("backend.checkin.load_config", return_value={}):
            engine = CheckinEngine()
        with mock.patch.object(engine, "_login"), mock.patch.object(engine, "_api_checkin", return_value={
                "code": 400, "already_checked": True, "reward_fish": 3, "today_fish": 3}):
            result = engine.execute("u", "p")
        self.assertTrue(result["already_checked"])
        self.assertEqual(result["fortune"]["result_text"], "3")
