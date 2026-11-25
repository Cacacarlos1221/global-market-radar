import datetime as dt
from contextlib import closing
import json
from unittest.mock import patch
from pathlib import Path
import tempfile
import unittest
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import radar

class RadarTests(unittest.TestCase):
    def test_sessions(self):
        for h,m,expected in [(9,14,"idle"),(9,15,"preopen"),(9,30,"open"),
            (11,30,"open"),(11,31,"idle"),(12,0,"idle"),(13,0,"open"),
            (15,0,"open"),(15,1,"close"),(15,11,"idle")]:
            self.assertEqual(radar.session(dt.datetime(2026,11,25,h,m)),expected)
    def test_expected_minutes(self):
        self.assertEqual(len(radar.expected_times("15:00:00")),240)
        self.assertEqual(len(radar.expected_times("11:30:00")),120)
        self.assertFalse(radar.market_bar("2026-11-25 12:00:00"))
    def test_normalization(self):
        item={"时间":"2026-11-25 09:31:00","开盘":10,"收盘":10,"最高":10.1,
              "最低":9.9,"成交量":10,"成交额":10000}
        args=("600000",[item],"2026-11-25 09:31:00","2026-11-25 09:32:00")
        rows=radar.normalize(*args)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0][6],1000)
        self.assertEqual(rows[0][7],10000)
        self.assertEqual(radar.normalize("600000",[item],"2026-11-25 09:30:00","x"),[])
        self.assertEqual(radar.normalize("600000",[dict(item,成交额=100)],args[2],args[3]),[])
    def test_missing_and_upsert(self):
        old=radar.HOME
        try:
            with tempfile.TemporaryDirectory() as tmp:
                radar.HOME=Path(tmp)
                conn=radar.db()
                t=dt.datetime(2026,11,25,9,32,tzinfo=radar.TZ)
                self.assertEqual(radar.features(conn,{"code":"600000","name":"X"},t,[],"09:31:00")["status"],"missing")
                row=("600000","2026-11-25 09:31:00",10,10,10,10,1000,10000,"2026-11-25 09:32:00")
                radar.save(conn,[row]); radar.save(conn,[row])
                self.assertEqual(conn.execute("select count(*) from bars").fetchone()[0],1)
                f=radar.features(conn,{"code":"600000","name":"X"},t,[],"09:31:00")
                self.assertEqual(f["vwap"],10)
                self.assertIsNone(f["score"])
                conn.close()
        finally:
            radar.HOME=old
    def test_sina_shares_auction_and_partial_coverage(self):
        self.assertEqual(len(radar.expected_times("15:00:00", radar.SINA)), 238)
        item = {"时间": "2026-11-25 09:31:00", "开盘": 10, "收盘": 10,
                "最高": 10, "最低": 10, "成交量": 123, "成交额": 1230}
        rows = radar.normalize("600000", [item], "2026-11-25 10:00:00", "x", radar.SINA)
        self.assertEqual(rows[0][6:8], (123, 1230))
        with tempfile.TemporaryDirectory() as tmp, patch.object(radar, "HOME", Path(tmp)):
            with closing(radar.db()) as conn:
                radar.save(conn, rows, radar.SINA)
                t = dt.datetime(2026, 11, 25, 9, 34, tzinfo=radar.TZ)
                f = radar.features(conn, {"code": "600000", "name": "X"}, t, [], "09:33:00")
                self.assertEqual(f["status"], "incomplete")
                self.assertAlmostEqual(f["minute_coverage"], 1/3)
                self.assertIsNone(f["vwap"])

    def test_signal_is_frozen_and_export_recoverable(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(radar, "HOME", Path(tmp)):
            with patch.object(radar, "OUT", Path(tmp)/"output"), closing(radar.db()) as conn:
                t = dt.datetime(2026, 11, 25, 14, 31, 20, tzinfo=radar.TZ)
                item = {"code": "600000", "status": "ok", "score": 5}
                radar.freeze(conn, t, [item], {})
                path = radar.OUT/"signals"/"2026-11-25_1430.json"
                saved = json.loads(path.read_text())
                path.unlink()
                radar.freeze(conn, t.replace(hour=15), [dict(item, score=1)], {})
                self.assertEqual(json.loads(path.read_text()), saved)
                self.assertEqual(saved["generated_at"], "2026-11-25 14:31:20")

    def test_legacy_database_migration(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(radar, "HOME", Path(tmp)):
            with closing(radar.sqlite3.connect(Path(tmp)/"market.sqlite")) as conn:
                conn.executescript(radar.SCHEMA.replace("source TEXT NOT NULL DEFAULT 'eastmoney', ", ""))
                conn.execute("INSERT INTO bars VALUES(?,?,?,?,?,?,?,?,?)",
                             ("600000", "2026-11-25 09:31:00", 10, 10, 10, 10, 100, 1000, "x"))
                conn.commit()
            with closing(radar.db()) as conn:
                self.assertEqual(conn.execute("SELECT source FROM bars").fetchone()[0], radar.EASTMONEY)

if __name__=="__main__":
    unittest.main()
