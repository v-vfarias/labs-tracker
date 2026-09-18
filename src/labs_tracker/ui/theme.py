"""Load the packaged stylesheet independently of the working directory."""
from importlib.resources import files

from nicegui import ui


def stylesheet() -> str:
    return files("labs_tracker.ui").joinpath("assets", "tracker.css").read_text(encoding="utf-8")


def apply_theme() -> None:
    ui.add_head_html(f"<style>{stylesheet()}</style>")
