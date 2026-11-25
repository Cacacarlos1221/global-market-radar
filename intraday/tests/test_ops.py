import datetime as dt
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ops
import radar


class OperationsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        home = Path(temp.name)
        self.home = home
        self.out = home / "output"
        self.out.mkdir()
        for name, value in (("HOME", home), ("OUT", self.out), ("CONFIG", home / "watchlist.json")):
            patched = patch.object(radar, name, value)
            patched.start()
            self.addCleanup(patched.stop)
        self.t = dt.datetime(2026, 11, 25, 14, 31, tzinfo=radar.TZ)

    def test_service_states_and_awake_window(self):
        self.assertEqual(ops.status(self.t)["state"], "interrupted")
        self.assertFalse(ops.awake_window(self.t))
        day = self.t.date().isoformat()
        radar.atomic(self.home / "calendar.json", {"checked": day, "dates": [day]})
        radar.atomic(self.home / "heartbeat.json", {"time": radar.stamp(self.t), "result": "ok"})
        self.assertTrue(ops.awake_window(self.t))
        self.assertEqual(ops.status(self.t)["state"], "stale")
        radar.atomic(self.out / "latest.json", {"phase": "open", "generated_at": radar.stamp(self.t),
                                              "stocks": [{"status": "ok"}]})
        self.assertEqual(ops.status(self.t)["state"], "live")
        self.assertTrue(ops.awake_window(self.t.replace(hour=12)))
        self.assertFalse(ops.awake_window(self.t.replace(hour=16)))
        self.assertEqual(ops.status(self.t.replace(hour=16))["state"], "closed")
        (self.home / "paused").touch()
        self.assertFalse(ops.awake_window(self.t))

    def test_remote_stocks_preserve_local_options_and_reject_bad_codes(self):
        local = {"stocks": [{"code":"600000","name":"本地"}], "provider":"sina", "workers":2,
                 "request_timeout_seconds":8, "cycle_timeout_seconds":50, "remote_watchlist":True,
                 "sync":{"enabled":False}}
        radar.atomic(radar.CONFIG, local)
        radar.atomic(self.home / "remote_stocks.json", {"stocks":[{"code":"000001","name":"远程"}],
                                                       "provider":"eastmoney", "sync":{"enabled":True}})
        cfg = radar.load_config()
        self.assertEqual(cfg["stocks"][0]["code"], "000001")
        self.assertEqual(cfg["provider"], "sina")
        self.assertEqual(cfg["sync"], local["sync"])
        radar.atomic(self.home / "remote_stocks.json", {"stocks":[{"code":"invalid","name":"bad"}]})
        self.assertEqual(radar.load_config()["stocks"], local["stocks"])

    @patch.object(ops, "gh")
    def test_upload_requires_both_flags(self, gh):
        with patch.object(radar, "load_config", return_value={"sync":{"enabled":True}}):
            ops.sync()
            with self.assertRaises(ValueError):
                ops.sync(force=True)
        gh.assert_not_called()

    @patch.object(ops, "gh")
    def test_atomic_upload_scopes_files_and_records_success(self, gh):
        gh.return_value = {"data":{"createCommitOnBranch":{"commit":{"oid":"new"}}}}
        (self.home / "market.sqlite").touch()
        (self.out / "extra.json").touch()
        radar.atomic(self.out / "latest.json", {"stocks":[]})
        files = ops.upload_files(self.t)
        self.assertEqual(set(files), {"intraday/latest.json", "intraday/status.json"})
        ops.upload("example/global-market-radar-data", "main", "old", files, {}, [], self.t)
        args = gh.call_args.kwargs["data"]["variables"]["input"]
        self.assertEqual(args["expectedHeadOid"], "old")
        paths = {x["path"] for x in args["fileChanges"]["additions"]}
        self.assertEqual(paths, set(files) | {ops.MANIFEST})
        self.assertEqual(json.loads((self.home / "last_sync.json").read_text())["commit"], "new")

    @patch.object(ops, "gh")
    def test_failed_sync_keeps_last_success_and_backs_off(self, gh):
        gh.side_effect = RuntimeError("offline")
        cfg = {"sync":{"enabled":True, "data_license_confirmed":True,
                       "repository":"example/global-market-radar-data"}}
        day = self.t.date().isoformat()
        radar.atomic(self.home / "calendar.json", {"checked":day,"dates":[day]})
        previous = {"time": radar.stamp(self.t-dt.timedelta(minutes=10)), "commit":"prior"}
        radar.atomic(self.home / "last_sync.json", previous)
        with patch.object(radar, "load_config", return_value=cfg), patch.object(radar, "now", return_value=self.t):
            with self.assertRaises(RuntimeError):
                ops.sync()
            ops.sync()
        self.assertEqual(gh.call_count, 1)
        self.assertEqual(ops.cached(self.home / "last_sync.json"), previous)
        self.assertTrue(ops.cached(self.home / "sync_error.json")["upload_failed"])

    def test_signal_priority_key_survives_session_exit(self):
        payload = {"market_day":"2026-11-25", "phase":"close"}
        signal = self.out / "signals" / "2026-11-25_1430.json"
        radar.atomic(signal, {})
        self.assertEqual(ops.critical_key(self.t.replace(hour=15, minute=5), payload),
                         ["2026-11-25_1430", "2026-11-25_close"])
        self.assertEqual(ops.critical_key(self.t.replace(hour=15, minute=11), payload),
                         ["2026-11-25_1430", "2026-11-25_final"])

    def test_dashboard_uses_snapshot_and_escapes_stock_names(self):
        radar.atomic(self.out / "latest.json", {"phase":"historical", "stocks":[
            {"name":"<script>stock</script>","code":"600000","status":"ok","price":10,"change_pct":2.5}]})
        with patch.object(radar, "now", return_value=self.t.replace(hour=16)):
            page = ops.dashboard().decode()
        self.assertIn("历史验收快照", page)
        self.assertIn("&lt;script&gt;stock&lt;/script&gt;", page)
        self.assertIn("+2.50%", page)
        self.assertIn("/radar.css", page)
