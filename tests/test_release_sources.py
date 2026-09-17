import unittest
from datetime import datetime, timezone
from unittest.mock import Mock

from labs_tracker.models import PRODUCT_VALUES
from labs_tracker.release_sources import PRODUCT_SOURCES, check_source_url, save_source_urls, source_for_product, source_validation, validate_source


class FakeResponse:
    def __init__(self, body: str, url: str, status: int = 200):
        self.body = body.encode()
        self.url = url
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self, limit: int):
        return self.body[:limit]

    def geturl(self):
        return self.url

    def getcode(self):
        return self.status


class ReleaseSourceTests(unittest.TestCase):
    def test_repo_lists_all_sources_and_aggregates_validation(self):
        from labs_tracker.web import _product_source_signal, _repo_products

        db = Mock()
        db.productSources.find_one.return_value = None
        products = _repo_products("MicrosoftLearning/mslearn-devops", [])
        self.assertEqual(set(products), {"Azure DevOps", "GitHub", "GitHub Actions", "GitHub Copilot"})
        db.sourceValidations.find_one.side_effect = lambda query: {"url": PRODUCT_SOURCES[query["product"]]["url"], "status": "Validated"}
        result = _product_source_signal(db, products)
        self.assertEqual(result["status"], "Validated")
        self.assertEqual(result["summary"], "4 of 4 sources validated")
        self.assertEqual([source["url"] for source in result["sources"]], [PRODUCT_SOURCES[product]["url"] for product in products])
        db.sourceValidations.find_one.side_effect = lambda query: None if query["product"] == "GitHub Copilot" else {"url": PRODUCT_SOURCES[query["product"]]["url"], "status": "Validated"}
        result = _product_source_signal(db, products)
        self.assertEqual(result["status"], "Needs attention")
        self.assertEqual(result["summary"], "3 of 4 sources validated")
        self.assertEqual(len(result["sources"]), 4)
        self.assertEqual(_product_source_signal(db, ["Unknown"])["sources"][0]["status"], "Not configured")
        self.assertEqual(_product_source_signal(db, [])["status"], "Not configured")

    def test_every_product_has_an_authoritative_source(self):
        self.assertEqual(set(PRODUCT_SOURCES), set(PRODUCT_VALUES))

    def test_validator_accepts_current_first_party_document(self):
        now = datetime(2026, 9, 17, tzinfo=timezone.utc)

        def opener(request, timeout):
            return FakeResponse(
                "<title>What's new in Microsoft Foundry</title><main>September 2026</main>",
                "https://devblogs.microsoft.com/foundry/",
            )

        result = validate_source("Foundry", opener=opener, now=now)

        self.assertEqual(result["status"], "Validated")
        self.assertEqual(result["latestPublicDate"], datetime(2026, 9, 1, tzinfo=timezone.utc))
        self.assertEqual(len(result["contentHash"]), 64)

    def test_validator_rejects_untrusted_redirect(self):
        now = datetime(2026, 9, 17, tzinfo=timezone.utc)

        def opener(request, timeout):
            return FakeResponse(
                "<title>Microsoft Foundry Blog</title><main>Latest posts September 2026</main>",
                "https://example.com/copied-release-notes",
            )

        result = validate_source("Foundry", opener=opener, now=now)

        self.assertEqual(result["status"], "Invalid")
        self.assertIn("untrusted host", result["reason"])

    def test_foundry_default_is_specific_roundup(self):
        self.assertEqual(source_for_product("Foundry")["url"], "https://devblogs.microsoft.com/foundry/whats-new-in-microsoft-foundry-july-august-2026/")

    def test_edited_url_is_validated_and_old_result_is_not_reused(self):
        db = Mock()
        url = "https://devblogs.microsoft.com/foundry/whats-new-in-microsoft-foundry-june-2026/"
        db.productSources.find_one.return_value = {"url": url}
        db.sourceValidations.find_one.return_value = {"url": PRODUCT_SOURCES["Foundry"]["url"], "status": "Validated"}
        self.assertEqual(source_validation(db, source_for_product("Foundry", db)), {})
        opener = Mock(return_value=FakeResponse("<title>What's new in Microsoft Foundry</title><main>June 2026</main>", url))
        result = validate_source("Foundry", db=db, opener=opener, now=datetime(2026, 9, 17, tzinfo=timezone.utc))
        self.assertEqual(opener.call_args.args[0].full_url, url)
        self.assertEqual(result["status"], "Validated")
        db.sourceValidations.find_one.return_value = result
        self.assertEqual(source_validation(db, source_for_product("Foundry", db)), result)

    def test_source_edit_checks_all_urls_before_writing(self):
        db = Mock()
        db.productSources.find_one.return_value = None
        url = "https://devblogs.microsoft.com/foundry/whats-new-in-microsoft-foundry-june-2026/"
        with self.assertRaises(ValueError):
            save_source_urls(db, {"Foundry": url, "GitHub": "http://localhost/private"})
        db.productSources.update_one.assert_not_called()
        save_source_urls(db, {"Foundry": url})
        db.productSources.update_one.assert_called_once_with({"_id": "Foundry"}, {"$set": {"url": url}}, upsert=True)
        for invalid in ("javascript:alert(1)", "https://example.com", "https://user:secret@github.com", "https://github.com:8000"):
            with self.assertRaises(ValueError):
                check_source_url(invalid)

    def test_validator_rejects_wrong_document(self):
        now = datetime(2026, 9, 17, tzinfo=timezone.utc)

        def opener(request, timeout):
            return FakeResponse(
                "<title>Microsoft Learn</title><main>September 2026 documentation</main>",
                "https://learn.microsoft.com/en-us/",
            )

        result = validate_source("Foundry", opener=opener, now=now)

        self.assertEqual(result["status"], "Invalid")
        self.assertIn("page identity", result["reason"])

    def test_validator_rejects_stale_document(self):
        now = datetime(2026, 9, 17, tzinfo=timezone.utc)

        def opener(request, timeout):
            return FakeResponse(
                "<title>Microsoft Foundry Blog</title><main>Latest posts January 2024</main>",
                "https://devblogs.microsoft.com/foundry/",
            )

        result = validate_source("Foundry", opener=opener, now=now)

        self.assertEqual(result["status"], "Invalid")
        self.assertIn("more than 400 days old", result["reason"])


if __name__ == "__main__":
    unittest.main()
