import unittest
from unittest.mock import Mock, patch

from typer.testing import CliRunner

from labs_tracker import cli


class CLITests(unittest.TestCase):
    def setUp(self):
        self.runner = CliRunner()

    def test_help_lists_existing_commands(self):
        result = self.runner.invoke(cli.app, ["--help"])
        self.assertEqual(result.exit_code, 0, result.output)
        for command in ("sync", "simplify", "classify", "sources-validate", "web"):
            self.assertIn(command, result.output)

    def test_simplify_requires_explicit_confirmation(self):
        with patch.object(cli, "simplify_collections") as simplify:
            result = self.runner.invoke(cli.app, ["simplify"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("destructive", result.output)
        simplify.assert_not_called()

    def test_sync_forwards_limit(self):
        with patch.object(cli, "run_sync", return_value={"repoCount": 1, "issueCount": 2}) as sync:
            result = self.runner.invoke(cli.app, ["sync", "--closed-issue-limit", "7"])
        self.assertEqual(result.exit_code, 0, result.output)
        sync.assert_called_once_with(closed_issue_limit=7)

    def test_classify_preserves_evidence_and_updates_only_cli_fields(self):
        item = {"issueId": "owner/repo#1", "state": "Open", "title": "Issue",
                "typeOfIssue": "Unknown", "resolution": "Unknown", "status": "Open",
                "handlingStage": "Raised", "externalResponse": "Existing evidence"}
        database = Mock()
        database.issues.find.return_value.sort.return_value.limit.return_value = [item]
        with patch.object(cli, "_db", return_value=database), \
             patch.object(cli, "_choose", side_effect=["SDK/code issues", "Unknown", "Open", "Investigating"]), \
             patch.object(cli.typer, "prompt", side_effect=["1", "Investigate", "2026-09-18"]):
            result = self.runner.invoke(cli.app, ["classify", "--limit", "3"])
        self.assertEqual(result.exit_code, 0, result.output)
        database.issues.find.return_value.sort.return_value.limit.assert_called_once_with(3)
        query, update = database.issues.update_one.call_args.args
        self.assertEqual(query, {"issueId": item["issueId"]})
        self.assertEqual(update["$set"]["typeOfIssue"], "SDK/code issues")
        self.assertNotIn("externalResponse", update["$set"])
        self.assertNotIn("title", update["$set"])
        self.assertEqual(update["$push"]["handlingHistory"]["evidence"]["externalResponse"], "Existing evidence")