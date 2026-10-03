import copy
import threading
import unittest
from unittest import mock

from backend import app, progress, transfer
from backend.scheduler import CheckinScheduler
from tests.test_transfer import CONFIG, SETTINGS


class TransferAPITest(unittest.TestCase):
    def setUp(self):
        self.client = app.app.test_client()

    def test_invalid_requests_never_start_work(self):
        with mock.patch.object(app, "load_config", return_value=CONFIG), mock.patch.object(transfer, "start_batch") as start:
            for body in ([], {}, {**SETTINGS, "batch_id": "bad"}, {**SETTINGS, "batch_id": "00000000-0000-0000-0000-000000000001", "amount": 0}):
                with self.subTest(body=body):
                    self.assertEqual(self.client.post('/api/transfer', json=body).status_code, 400)
            start.assert_not_called()

    def test_async_response_and_busy_response(self):
        body = {**SETTINGS, "batch_id": "00000000-0000-0000-0000-000000000001"}
        with mock.patch.object(app, "load_config", return_value=CONFIG), mock.patch.object(transfer, "start_batch", return_value="task"):
            response = self.client.post('/api/transfer', json=body)
            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.json['task_id'], 'task')
        with mock.patch.object(app, "load_config", return_value=CONFIG), mock.patch.object(transfer, "start_batch", side_effect=transfer.TransferBusyError('busy')):
            self.assertEqual(self.client.post('/api/transfer', json=body).status_code, 409)

    def test_batch_lock_blocks_overlap_and_releases_after_error(self):
        entered, release = threading.Event(), threading.Event()
        original_release = transfer._batch_lock
        def run(*args):
            entered.set()
            release.wait(3)
            raise ValueError('simulated failure')
        with mock.patch.object(transfer, 'run_batch', side_effect=run):
            task_id = transfer.start_batch(CONFIG, SETTINGS, 'batch')
            self.assertTrue(entered.wait(3))
            try:
                with self.assertRaises(transfer.TransferBusyError):
                    transfer.start_batch(CONFIG, SETTINGS, 'other')
            finally:
                release.set()
            # 等锁释放意味着异步任务已经完成；无时间延迟断言。
            self.assertTrue(original_release.acquire(timeout=3))
            original_release.release()
        data = progress.get_progress(task_id)
        self.assertTrue(data['done'])
        self.assertEqual(data['error'], 'simulated failure')

    def test_config_update_preserves_transfer_settings(self):
        config = {**CONFIG, 'transfer': {**SETTINGS, 'enabled': False}}
        captured = {}
        with mock.patch.object(app, 'load_config', return_value=config), \
                mock.patch.object(app, 'save_config', side_effect=lambda c: captured.update(copy.deepcopy(c))), \
                mock.patch.object(app, 'get_scheduler'):
            response = self.client.post('/api/config', json={'site': CONFIG['site']})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured['transfer'], config['transfer'])

    def test_invalid_schedule_is_rejected_before_saving_credentials(self):
        with mock.patch.object(app, 'save_accounts') as save_accounts:
            with self.assertRaises(ValueError):
                app.save_config({'transfer': {**SETTINGS, 'enabled': True, 'times': ['25:00']},
                                 'accounts': CONFIG['accounts']})
            save_accounts.assert_not_called()


class TransferSchedulerTest(unittest.TestCase):
    def test_transfer_runs_when_checkin_schedule_is_disabled(self):
        config = {**CONFIG, 'schedule': {'enabled': False},
                  'transfer': {**SETTINGS, 'enabled': True, 'times': ['00:05', '12:00']}}
        scheduler = CheckinScheduler()
        with mock.patch('backend.scheduler.load_config', return_value=config):
            scheduler.start()
        try:
            self.assertEqual({j.id for j in scheduler.scheduler.get_jobs()}, {'transfer_0005', 'transfer_1200'})
            self.assertIsNone(scheduler.get_next_run())
            self.assertIsNotNone(scheduler.get_next_run('transfer_'))
            scheduler._remove_all_jobs()
            self.assertEqual(scheduler.scheduler.get_jobs(), [])
        finally:
            scheduler.shutdown()

    def test_scheduled_slot_reuses_same_batch_and_disabled_callback_does_nothing(self):
        config = {**CONFIG, 'transfer': {**SETTINGS, 'enabled': True}}
        scheduler = CheckinScheduler()
        with mock.patch('backend.scheduler.load_config', return_value=config), mock.patch('backend.scheduler.start_batch') as start:
            scheduler._transfer_job('00:05')
            scheduler._transfer_job('00:05')
            self.assertEqual(start.call_args_list[0].args[2], start.call_args_list[1].args[2])
            config['transfer']['enabled'] = False
            scheduler._transfer_job('00:05')
            self.assertEqual(start.call_count, 2)
