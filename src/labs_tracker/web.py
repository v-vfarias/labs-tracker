"""Stable entry point for the local NiceGUI tracker."""
from nicegui import ui

from .config import load_settings
from .db import ensure_indexes, get_database
from .ui.app import build_ui


def run(host: str = "127.0.0.1", port: int = 8080):
    @ui.page("/")
    def _home():
        db = get_database(load_settings())
        ensure_indexes(db)
        build_ui(db)

    ui.run(host=host, port=port, title="Labs Tracker", reload=False)


if __name__ == "__main__":
    run()
