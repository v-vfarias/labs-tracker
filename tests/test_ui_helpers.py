import unittest
from datetime import datetime, timezone

from labs_tracker import web
from labs_tracker.services.reports import _issue_query
from test_models_tasks import FakeCollection


class UIHelperTests(unittest.TestCase):
    def test_unknown_classification_includes_missing_and_unrecognized_values(self):
        records = [
            {"id": "missing"},
            {"id": "unknown", "typeOfIssue": "Unknown"},
            {"id": "invalid", "typeOfIssue": "Something else"},
            {"id": "legacy", "typeOfIssue": "SDK/code update"},
            {"id": "current", "typeOfIssue": "SDK/code issues"},
        ]
        collection = FakeCollection(records)
        query = {"typeOfIssue": web._issue_type_query("Unknown")}
        self.assertEqual([row["id"] for row in collection.find(query)], ["missing", "unknown", "invalid"])
        query = {"typeOfIssue": web._issue_type_query("SDK/code issues")}
        self.assertEqual([row["id"] for row in collection.find(query)], ["legacy", "current"])

    def test_resolution_aliases_and_missing_classification(self):
        self.assertIn("Updated code/sample", web._resolution_query("Fixed in lab")["$in"])
        self.assertNotIn("Unknown", web._resolution_query("Unknown")["$nin"])
        self.assertEqual(web._needs_classification_query(), {"$or": [
            {"typeOfIssue": web._issue_type_query("Unknown")},
            {"resolution": web._resolution_query("Unknown")},
        ]})

    def test_report_query_remains_literal_and_issue_only(self):
        self.assertEqual(_issue_query({"typeOfIssue": "SDK/code issues", "state": "All"}),
                         {"kind": "Issue", "typeOfIssue": "SDK/code issues"})
        self.assertEqual(_issue_query({"unexpected": "value"}), {"kind": "Issue"})

    def test_product_display_defaults_and_alias_deduplication(self):
        repo_id = "MicrosoftLearning/mslearn-ai-language"
        self.assertEqual(web._repo_products(repo_id, []), ["Foundry"])
        self.assertEqual(web._repo_products(repo_id, ["Azure AI Language", "Foundry", "PowerBI"]), ["Foundry", "Power BI"])
        self.assertEqual(web._repo_products(None, None), [])

    def test_datetime_input_and_display_contracts(self):
        self.assertIsNone(web._parse_dt("  "))
        self.assertEqual(web._parse_dt("2026-09-18T12:00:00+02:00"), datetime(2026, 9, 18, 10, tzinfo=timezone.utc))
        self.assertEqual(web._parse_dt("2026-09-18"), datetime(2026, 9, 18, tzinfo=timezone.utc))
        self.assertEqual(web._fmt_dt(None), "")
        self.assertEqual(web._fmt_table_dt("2026-09-18T12:00:00Z"), "2026-09-18 12:00")
        with self.assertRaises(ValueError):
            web._parse_dt("not a date")

    def test_csv_and_table_event_shapes(self):
        self.assertEqual(web._parse_csv(" Foundry, ,GitHub "), ["Foundry", "GitHub"])
        self.assertEqual(web._parse_csv([" Foundry ", None, ""]), ["Foundry"])
        self.assertEqual(web._parse_csv(None), [])
        row = {"issueId": "owner/repo#3"}
        for args in ({"row": row}, [None, row], (None, row)):
            self.assertEqual(web._table_event_row(args), row)
        for args in (None, [], {"row": "invalid"}, row):
            self.assertEqual(web._table_event_row(args), {})

    def test_links_and_chart_limits(self):
        self.assertEqual(web._issue_url("owner/repo#3", "PR"), "https://github.com/owner/repo/pull/3")
        self.assertIsNone(web._issue_url("owner/repo"))
        self.assertEqual(web._issue_number("owner/repo#3"), "#3")
        rows = [{"label": str(index), "count": index} for index in range(10)]
        self.assertEqual(web._chart_options("Title", rows)["series"][0]["data"], list(range(8)))
        self.assertEqual(web._chart_options("Title", [], chart_type="donut")["series"][0]["data"], [])