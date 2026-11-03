import unittest
from scripts.render import render_report, validate_analysis

class ReportSectionsTests(unittest.TestCase):
    def setUp(self):
        self.raw = {
            "report_date": "2026-11-03", "collected_at_utc": "2026-11-03T00:15:00Z",
            "quotes": [], "news": [{"headline": "Unverified <b>headline</b>",
             "source": "RSS", "published_at_utc": "2026-11-03T00:00:00Z",
             "url": "https://example.org/rss"}]
        }
        self.analysis = {
            "report_date": "2026-11-03", "market_summary": "US market lower",
            "a_share_bias": "mixed", "a_share_outlook": "Observe",
            "a_share_sectors": [], "risks": [], "uncertainty": "medium",
            "news_digest": {
                "overview": "Important news in context",
                "items": [{"title": "Key news", "summary": "Confirmed event",
                           "market_impact": "May weigh on AUD", "source_ids": ["S1"],
                           "importance": "high"}]
            },
            "news_sources": [{"id": "S1", "title": "Original news article",
                             "publisher": "Publisher", "url": "https://example.com/article",
                             "verification": "reported"}]
        }

    def test_new_sections_and_collapsed_raw_news(self):
        validate_analysis(self.analysis)
        html = render_report(self.raw, self.analysis)
        self.assertIn("04 / 国际重要新闻综述", html)
        self.assertIn("05 / A股开盘前研判", html)
        self.assertIn("06 / 新闻来源与参考资料", html)
        self.assertNotIn("<h2>06 / 数据质量</h2>", html)
        self.assertIn('href="#ref-S1"', html)
        self.assertIn('id="ref-S1"', html)
        self.assertIn("<details>", html)
        self.assertIn("数据状态：0/0", html)
        self.assertIn("&lt;b&gt;headline&lt;/b&gt;", html)

    def test_legacy_analysis_still_renders(self):
        old = {"market_summary": "Legacy", "evidence_urls": ["https://example.com/old"]}
        html = render_report(self.raw, old)
        self.assertIn("本期尚无经过核验和筛选", html)
        self.assertIn("历史分析参考资料", html)

    def test_missing_analysis_safe(self):
        html = render_report(self.raw)
        self.assertIn("04 / 国际重要新闻综述", html)
        self.assertIn("未核实的 RSS 标题不会自动转换成市场结论", html)

    def test_new_digest_requires_valid_citations(self):
        self.analysis["news_digest"]["items"][0]["source_ids"] = ["MISSING"]
        with self.assertRaises(ValueError):
            validate_analysis(self.analysis)

    def test_malicious_source_is_not_linked(self):
        self.analysis["news_sources"][0]["url"] = 'javascript:alert(1)'
        with self.assertRaises(ValueError):
            validate_analysis(self.analysis)
        html = render_report(self.raw, self.analysis)
        self.assertNotIn('href="javascript:', html)

if __name__ == "__main__":
    unittest.main()
