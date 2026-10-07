"""Long-running UI actions and their client-local lifecycle."""
from collections.abc import Callable, Sequence

from nicegui import run as nicegui_run, ui

from ..integrations.release_sources import validate_all_sources
from ..services.sync import sync
from ..config import load_settings
from ..services.release_checks import check_release_notes, get_release_check, mark_reviewed
from ..services.tracking import get_repo, product_source_statuses
from ..domain.products import repo_products


class PageActions:
    def __init__(
        self,
        db,
        sync_buttons: Sequence[ui.button],
        source_validate_button: ui.button,
        on_sync: Callable[[], None],
        on_sources: Callable[[], None],
    ):
        self.db = db
        self.sync_buttons = sync_buttons
        self.source_validate_button = source_validate_button
        self.on_sync = on_sync
        self.on_sources = on_sources
        self.sync_state = {"running": False, "dots": 0, "notification": None, "timer": None}

    def release_state(self, repo_id: str) -> dict:
        repo = get_repo(self.db, repo_id) or {}
        return {**get_release_check(self.db, repo_id),
            "sourceStatuses": product_source_statuses(self.db, repo_products(repo_id, repo.get("products") or []))}

    def release_enabled(self) -> bool:
        return load_settings().release_check.enabled

    async def run_release_check(self, repo_id: str) -> dict:
        await check_release_notes(self.db, repo_id)
        self.on_sources()
        return await nicegui_run.io_bound(self.release_state, repo_id)

    async def review_release(self, repo_id: str, finding_ids: list[str], note: str, version: int) -> dict:
        await nicegui_run.io_bound(mark_reviewed, self.db, repo_id, finding_ids, note, version)
        self.on_sources()
        return await nicegui_run.io_bound(self.release_state, repo_id)

    async def run_issue_sync(self):
        if self.sync_state["running"]:
            return

        def set_sync_buttons(running: bool):
            for button in self.sync_buttons:
                if running:
                    button.disable()
                    button.classes("syncing-button")
                else:
                    button.enable()
                    button.classes(remove="syncing-button")

        def update_sync_message():
            notification = self.sync_state["notification"]
            if not self.sync_state["running"] or notification is None:
                return
            self.sync_state["dots"] = self.sync_state["dots"] % 3 + 1
            notification.message = f"Syncing issues{'.' * self.sync_state['dots']}"
            notification.update()

        self.sync_state["running"] = True
        self.sync_state["dots"] = 0
        set_sync_buttons(True)
        self.sync_state["notification"] = ui.notification(
            "Syncing issues",
            color="info",
            spinner=True,
            timeout=None,
        )
        self.sync_state["timer"] = ui.timer(0.45, update_sync_message)
        try:
            result = await nicegui_run.io_bound(sync)
        except Exception as error:
            ui.notify(f"Sync failed: {error}", color="negative", multi_line=True)
        else:
            ui.notify(f"Synced {result['repoCount']} repo(s), {result['issueCount']} issue records", color="positive")
            self.on_sync()
        finally:
            self.sync_state["running"] = False
            timer = self.sync_state.get("timer")
            if timer is not None:
                timer.cancel()
            notification = self.sync_state.get("notification")
            if notification is not None:
                notification.dismiss()
            self.sync_state["timer"] = None
            self.sync_state["notification"] = None
            set_sync_buttons(False)

    async def run_source_validation(self):
        self.source_validate_button.disable()
        notification = ui.notification("Validating authoritative sources", color="info", spinner=True, timeout=None)
        try:
            results = await nicegui_run.io_bound(validate_all_sources, self.db)
        except Exception as error:
            ui.notify(f"Source validation failed: {error}", color="negative", multi_line=True)
        else:
            failed = sum(result["status"] != "Validated" for result in results)
            ui.notify(
                f"Validated {len(results) - failed}/{len(results)} product sources",
                color="positive" if failed == 0 else "warning",
            )
            self.on_sources()
        finally:
            notification.dismiss()
            self.source_validate_button.enable()

