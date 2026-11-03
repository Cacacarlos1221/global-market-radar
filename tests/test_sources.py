import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from scripts.sources import normalize_quote, parse_bars, parse_rss
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
