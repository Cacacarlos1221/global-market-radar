import json
from unittest.mock import patch
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from scripts.sources import normalize_quote, parse_bars, parse_rss, eastmoney_index_quote, collect_quotes
from scripts.pipeline import append_unique, QUOTE_COLS

class SourceTests(unittest.TestCase):
    def test_parse_bars_rejects_null_and_zero(self):
        data = {"meta": {"exchangeTimezoneName": "America/New_York"},
                "timestamp": [1793640000, 1793726400, 1793812800],
                "indicators": {"quote": [{"close": [10.0, None, 12.0]}]}}
        bars = parse_bars(data)
        self.assertEqual([b["value"] for b in bars], [10.0, 12.0])
    def test_fx_intraday_reference_is_previous_daily(self):
        daily = [{"value": 4.60, "market_date": "2026-11-02", "observed_at_utc": "2026-11-02T21:00:00+00:00"},
                 {"value": 4.65, "market_date": "2026-11-03", "observed_at_utc": "2026-11-03T01:00:00+00:00"}]
        intraday = [{"value": 4.70, "market_date": "2026-11-03", "observed_at_utc": "2026-11-03T04:00:00+00:00"}]
        asset = {"key": "AUD_CNY", "symbol": "AUDCNY=X", "label": "test", "unit": "CNY/AUD", "category": "fx"}
        result = normalize_quote(asset, daily, intraday)
        self.assertEqual(result["reference_close"], 4.6)
        self.assertEqual(result["value_kind"], "intraday_observation")
    def test_ashare_live_bar_not_labeled_close(self):
        asset = {"key": "SSE", "symbol": "000001.SS", "label": "SSE", "unit": "points", "category": "cn_index"}
        daily = [{"value": 3500, "market_date": "2026-11-03", "observed_at_utc": "2026-11-03T01:30:00+00:00"}]
        live = normalize_quote(asset, daily, now=datetime(2026, 11, 3, 6, 45, tzinfo=timezone.utc))
        closed = normalize_quote(asset, daily, now=datetime(2026, 11, 3, 7, 30, tzinfo=timezone.utc))
        self.assertEqual(live["value_kind"], "daily_bar_live")
        self.assertEqual(closed["value_kind"], "daily_close")
    def test_eastmoney_uses_only_completed_cn_session(self):
        daily = {"data": {"code": "000001", "klines": [
            "2026-11-03,3624.58,3608.10,3624.58,3580.38",
            "2026-11-04,3605.39,3686.17,3686.17,3590.80",
            "2026-11-05,3680,3900,3900,3680"
        ]}}
        asset = {"key": "SSE", "symbol": "000001.SS", "label": "上证综指",
                 "unit": "points", "category": "cn_index"}
        at = datetime(2026, 11, 5, 0, 35, tzinfo=timezone.utc)
        with patch("scripts.sources.read_url", return_value=json.dumps(daily).encode()) as fetch:
            q = eastmoney_index_quote(asset, now=at)
        self.assertEqual(q["market_date"], "2026-11-04")
        self.assertAlmostEqual(q["value"], 3686.17)
        self.assertAlmostEqual(q["change_pct"], 2.1637, places=3)
        self.assertIsNone(q["observed_at_utc"])
        self.assertIn("secid=1.000001", fetch.call_args.args[0])

    def test_eastmoney_wrong_instrument_fails(self):
        asset = {"key": "SSE", "symbol": "000001.SS", "label": "SSE",
                 "unit": "points", "category": "cn_index"}
        with patch("scripts.sources.read_url", return_value=b'{"data":{"code":"000300","klines":[]}}'):
            with self.assertRaises(ValueError):
                eastmoney_index_quote(asset)

    def test_stale_yahoo_index_marked_not_ok(self):
        assets = [
            {"key": "SSE", "symbol": "000001.SS", "label": "SSE",
             "unit": "points", "category": "cn_index"},
            {"key": "CSI300", "symbol": "000300.SS", "label": "CSI",
             "unit": "points", "category": "cn_index"}
        ]
        def fake_yahoo(symbol, interval="1d", period="14d"):
            epoch = [1793669400, 1793755800] if symbol == "000001.SS" else [1793755800, 1793842200]
            return {"meta": {"exchangeTimezoneName": "Asia/Shanghai"},
                    "timestamp": epoch,
                    "indicators": {"quote": [{"close": [3608, 3686]}]}}
        with patch("scripts.sources.eastmoney_index_quote", side_effect=RuntimeError("Blocked")):
            with patch("scripts.sources.yahoo_chart", side_effect=fake_yahoo):
                with patch("scripts.sources.time.sleep"):
                    values = collect_quotes(assets)
        self.assertEqual(values[0]["status"], "stale")
        self.assertIn("older than peer", values[0]["error"])
        self.assertEqual(values[1]["status"], "ok")

    def test_rss_filter_and_id(self):
        xml = b"<rss><channel><item><title>Test market event</title><link>https://example.com/x</link><pubDate>Tue, 03 Nov 2026 02:00:00 GMT</pubDate><source>Example</source></item></channel></rss>"
        result = parse_rss(xml, "macro", datetime(2026, 11, 3, 3, tzinfo=timezone.utc))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["verification"], "rss_headline_unverified")
    def test_append_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "quotes.csv"
            row = {"report_date": "2026-11-03", "asset_key": "NASDAQ", "value": 1}
            append_unique(path, QUOTE_COLS, [row], ["report_date", "asset_key"])
            append_unique(path, QUOTE_COLS, [row], ["report_date", "asset_key"])
            self.assertEqual(len(path.read_text().splitlines()), 2)

if __name__ == "__main__":
    unittest.main()
