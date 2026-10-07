"""Replaceable async analysis boundary; the pilot starts without model calls."""
from __future__ import annotations


class MockReleaseAnalyzer:
    version = "mock-v2"
    backend = "mock"

    async def analyze(self, articles: list[dict], context: dict, changes: dict) -> dict:
        return {
            "backend": self.backend,
            "version": self.version,
            "status": "Mock",
            "impact": "Not assessed",
            "summary": [
                f"{len(articles)} official release article(s) captured.",
                f"{len(context['files'])} selected lab file(s) captured.",
                "Placeholder assessment: no model was called; potential lab impact has not been assessed.",
            ],
            "findings": [],
        }