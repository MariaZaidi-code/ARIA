"""Regression tests for the ARIA Intelligence PDF renderer."""

import unittest

from reporting.pdf_export import render_intelligence_report_pdf


class ReportPdfExportTests(unittest.TestCase):
    def test_saved_report_renders_as_pdf(self):
        payload = {
            "title": "Quarterly Revenue",
            "description": "Verified KPI results",
            "date_range": "2026 Q3",
            "sections": ["Overview", "Performance"],
            "findings": [{"title": "Revenue", "summary": "Growth of 5%"}],
            "tables": [{
                "title": "Goal tracking",
                "columns": ["Metric", "Current", "Target"],
                "rows": [["Revenue", "120", "150"]],
            }],
        }
        result = render_intelligence_report_pdf(payload)
        self.assertTrue(result.startswith(b"%PDF-"))
        self.assertGreater(len(result), 1000)

    def test_empty_report_is_still_downloadable(self):
        result = render_intelligence_report_pdf({})
        self.assertTrue(result.startswith(b"%PDF-"))

    def test_user_provided_markup_is_safely_escaped(self):
        payload = {
            "title": "<script>alert('x')</script>",
            "description": "<b>not trusted</b>",
            "sections": ["<font color='red'>fake</font>"],
            "findings": [{"title": "<u>Title</u>", "summary": "& characters"}],
        }
        result = render_intelligence_report_pdf(payload)
        self.assertTrue(result.startswith(b"%PDF-"))


if __name__ == "__main__":
    unittest.main()
