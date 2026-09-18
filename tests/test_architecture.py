import ast
import importlib
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


PACKAGE = Path(__file__).resolve().parents[1] / "src" / "labs_tracker"


class ArchitectureTests(unittest.TestCase):
    def test_public_compatibility_imports_reference_the_owning_implementation(self):
        for legacy, owner, name in [
            ("models", "domain.models", "normalize_issue_type"),
            ("workflow", "domain.workflow", "progress_update"),
            ("tasks", "services.tasks", "generate_tasks"),
            ("report", "services.reports", "generate_report"),
            ("sync", "services.sync", "sync"),
            ("sync", "services.maintenance", "simplify_collections"),
            ("release_sources", "integrations.release_sources", "validate_source"),
        ]:
            with self.subTest(module=legacy, symbol=name):
                old = importlib.import_module(f"labs_tracker.{legacy}")
                new = importlib.import_module(f"labs_tracker.{owner}")
                self.assertIs(getattr(old, name), getattr(new, name))

    def test_non_ui_packages_do_not_import_presentation(self):
        for directory in ("domain", "services", "integrations"):
            for path in (PACKAGE / directory).glob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    modules = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
                    for module in modules:
                        with self.subTest(path=path.name, module=module):
                            self.assertNotIn("nicegui", module.split("."))
                            self.assertNotIn("ui", module.split("."))
                            self.assertNotIn("web", module.split("."))

    def test_cli_import_does_not_load_nicegui(self):
        result = subprocess.run(
            [sys.executable, "-c", "import sys; import labs_tracker.cli; assert 'nicegui' not in sys.modules"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_domain_depends_only_on_standard_library_and_domain(self):
        for path in (PACKAGE / "domain").glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom) and node.level:
                    self.assertEqual(node.level, 1, path.name)
                    self.assertTrue((PACKAGE / "domain" / f"{node.module}.py").exists(), path.name)
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    modules = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module]
                    for module in modules:
                        self.assertIn(module.split(".")[0], sys.stdlib_module_names, path.name)

    def test_owning_packages_do_not_import_legacy_facades(self):
        facades = {"models", "workflow", "tasks", "report", "sync", "release_sources"}
        for directory in ("domain", "services", "integrations", "ui"):
            for path in (PACKAGE / directory).rglob("*.py"):
                package = "labs_tracker." + ".".join(path.parent.relative_to(PACKAGE).parts)
                for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                    if isinstance(node, ast.ImportFrom):
                        module = importlib.util.resolve_name("." * node.level + (node.module or ""), package) if node.level else node.module
                        self.assertNotIn(module, {f"labs_tracker.{name}" for name in facades}, path.name)

    def test_packaged_stylesheet_contains_screen_and_print_rules(self):
        from labs_tracker.ui.theme import stylesheet

        css = stylesheet()
        self.assertIn(".tracker-shell", css)
        self.assertIn("@media print", css)
        self.assertIn("@media", css)
        self.assertNotIn("<style>", css)

    def test_presentation_does_not_access_database_collections(self):
        def is_database(value):
            return (isinstance(value, ast.Name) and value.id == "db") or (isinstance(value, ast.Attribute) and value.attr == "db")

        paths = [PACKAGE / "web.py", PACKAGE / "cli.py", *(PACKAGE / "ui").rglob("*.py")]
        collection_names = {"repos", "issues", "productSources", "sourceValidations"}
        for path in paths:
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Attribute) and is_database(node.value):
                    self.assertNotIn(node.attr, collection_names, f"{path.name}:{node.lineno}")
                if isinstance(node, ast.Subscript) and is_database(node.value):
                    self.fail(f"Direct database indexing in {path.name}:{node.lineno}")

    def test_views_and_dialogs_do_not_import_coordinator_or_other_views(self):
        forbidden = {"labs_tracker.web", "labs_tracker.ui.app", "labs_tracker.ui.actions"}
        for directory in ("views", "dialogs"):
            for path in (PACKAGE / "ui" / directory).glob("*.py"):
                package = f"labs_tracker.ui.{directory}"
                for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                    if isinstance(node, ast.ImportFrom):
                        module = importlib.util.resolve_name("." * node.level + (node.module or ""), package) if node.level else node.module
                        modules = [module, *(f"{module}.{alias.name}" for alias in node.names)]
                    elif isinstance(node, ast.Import):
                        modules = [alias.name for alias in node.names]
                    else:
                        continue
                    for module in modules:
                        self.assertNotIn(module, forbidden, path.name)
                        self.assertFalse(module == "labs_tracker.ui.views" or module.startswith("labs_tracker.ui.views."), path.name)

    def test_web_entry_point_registers_page_and_initializes_database_lazily(self):
        from labs_tracker import web

        registered = {}

        def register(route):
            def decorator(handler):
                registered[route] = handler
                return handler
            return decorator

        db = Mock()
        with patch.object(web.ui, "page", side_effect=register), patch.object(web.ui, "run") as run, \
                patch.object(web, "load_settings", return_value="settings"), \
                patch.object(web, "get_database", return_value=db) as get_database, \
                patch.object(web, "ensure_indexes") as indexes, patch.object(web, "build_ui") as build:
            web.run(host="127.0.0.2", port=8091)
            run.assert_called_once_with(host="127.0.0.2", port=8091, title="Labs Tracker", reload=False)
            get_database.assert_not_called()
            registered["/"]()
            get_database.assert_called_once_with("settings")
            indexes.assert_called_once_with(db)
            build.assert_called_once_with(db)