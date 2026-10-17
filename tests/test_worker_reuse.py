import importlib.util
import pathlib
import sys
import threading
import unittest
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location('worker_launcher',ROOT/'ai-launcher.py')
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)

class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.app=a.LauncherUI(enable_tray=False,observe=False);self.app.hide()
    def tearDown(self):self.app.quit()

    def test_each_lane_reuses_one_thread(self):
        for executor in (self.app.telemetry_worker,self.app.policy_worker):
            ids={executor.submit(threading.get_ident).result(timeout=2) for _ in range(25)}
            self.assertEqual(len(ids),1)
            self.assertNotIn(threading.get_ident(),ids)

    def test_blocked_telemetry_does_not_delay_recovery_lane(self):
        entered=threading.Event();release=threading.Event()
        def blocked():entered.set();release.wait(3)
        future=self.app.telemetry_worker.submit(blocked)
        try:
            self.assertTrue(entered.wait(1))
            result=self.app.policy_worker.submit(lambda:'recovery ran').result(timeout=1)
            self.assertEqual(result,'recovery ran')
        finally:release.set();future.result(timeout=2)

    def test_refresh_remains_single_flight_while_worker_is_blocked(self):
        entered=threading.Event();release=threading.Event();calls=[]
        def summary():calls.append(1);entered.set();release.wait(3);return {}
        with patch.object(self.app.collector,'summary',side_effect=summary),patch.object(a,'observed_profile',return_value=(None,'Waiting for request')):
            try:
                self.app.refresh();self.assertTrue(entered.wait(1));self.app.refresh()
                self.assertEqual(len(calls),1)
            finally:
                release.set();self.app.telemetry_worker.submit(lambda:None).result(timeout=2)
        self.assertEqual(self.app.events.qsize(),1)

    def test_shutdown_rejects_new_work_and_polling_stops(self):
        self.assertTrue(self.app.quit())
        self.app.refresh();self.app.check_auto()
        for executor in (self.app.telemetry_worker,self.app.policy_worker):
            with self.assertRaises(RuntimeError):executor.submit(lambda:None)
        # tearDown must not call Tk after destruction.
        self.app.quit=lambda:True

if __name__=='__main__':unittest.main()
