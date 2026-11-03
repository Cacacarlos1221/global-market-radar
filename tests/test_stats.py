import unittest
from scripts.stats import pearson, daily_returns
from scripts.render import render_report

class ResearchTests(unittest.TestCase):
    def test_correlation(self):
        self.assertAlmostEqual(pearson([1, 2, 3], [2, 4, 6]), 1)
        self.assertIsNone(pearson([1, 1, 1], [3, 4, 5]))
        self.assertIsNone(pearson([1, 2], [3, 4]))
    def test_returns(self):
        values = {"2026-11-01": 100, "2026-11-02": 110}
        self.assertAlmostEqual(daily_returns(values)["2026-11-02"], 10)
    def test_html_escapes_news_headline(self):
        data = {"report_date": "2026-11-04", "collected_at_utc": "2026-11-04T00:00:00+00:00",
                "quotes": [], "news": [{"headline": "<script>bad()</script>", "url": "https://example.com",
                "source": "source", "topic": "macro", "published_at_utc": "2026-11-04T00:00:00Z"}]}
        html = render_report(data)
        self.assertNotIn("<script>bad()", html)
        self.assertIn("&lt;script&gt;", html)

if __name__ == "__main__":
    unittest.main()
