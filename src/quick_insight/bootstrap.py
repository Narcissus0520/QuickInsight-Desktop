from __future__ import annotations

import argparse
import os
from collections.abc import Sequence
from typing import cast

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from quick_insight import APP_NAME, APP_NAME_ZH, __version__
from quick_insight.infrastructure.cache_cleanup import cleanup_app_cache
from quick_insight.infrastructure.logging import configure_logging
from quick_insight.infrastructure.paths import AppPaths
from quick_insight.infrastructure.settings import AppSettings, load_settings
from quick_insight.ui.main_window import MainWindow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="quick-insight")
    parser.add_argument(
        "--smoke-seconds",
        type=float,
        default=0.0,
        help="Auto-exit after N seconds for launch smoke tests.",
    )
    parser.add_argument(
        "--theme",
        choices=("light", "dark"),
        default=None,
        help="Override the persisted theme for this launch.",
    )
    return parser


def run(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv or ()))
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")

    paths = AppPaths.default().ensure()
    logger = configure_logging(paths.log_dir)
    cleanup_report = cleanup_app_cache(paths)
    logger.info(
        "startup_cache_cleanup",
        extra={
            "operation": "startup_cleanup",
            "removed_paths": cleanup_report.removed_count,
            "removed_bytes": cleanup_report.removed_bytes,
        },
    )
    settings = _load_settings(paths)
    if args.theme is not None:
        settings = settings.with_theme(args.theme)

    app = QApplication.instance()
    owns_app = app is None
    app = QApplication([APP_NAME, *list(argv or ())]) if app is None else cast(QApplication, app)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName("QuickInsight")

    window = MainWindow(settings=settings, settings_path=paths.settings_file, paths=paths)
    window.show()
    window.setWindowTitle(APP_NAME_ZH)
    logger.info("app_started", extra={"operation": "startup", "version": __version__})

    if args.smoke_seconds > 0:
        QTimer.singleShot(int(args.smoke_seconds * 1000), app.quit)

    return app.exec() if owns_app else 0


def _load_settings(paths: AppPaths) -> AppSettings:
    return load_settings(paths.settings_file)
