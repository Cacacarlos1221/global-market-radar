import datetime as dt
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
if __name__=="__main__":
    unittest.main()
