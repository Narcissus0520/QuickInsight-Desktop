from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from quick_insight import APP_AUTHOR, APP_NAME

_platformdirs: Any | None
try:
    import platformdirs as _platformdirs
except ImportError:  # pragma: no cover - dependency is installed by setup_dev.ps1.
    _platformdirs = None


@dataclass(frozen=True)
class AppPaths:
    config_dir: Path
    cache_dir: Path
    temp_dir: Path
    log_dir: Path
    settings_file: Path

    @classmethod
    def default(cls) -> AppPaths:
        if _platformdirs is not None:
            config_dir = Path(_platformdirs.user_config_path(APP_NAME, APP_AUTHOR))
            cache_dir = Path(_platformdirs.user_cache_path(APP_NAME, APP_AUTHOR))
            log_dir = Path(_platformdirs.user_log_path(APP_NAME, APP_AUTHOR))
        else:
            local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
            root = local_app_data / APP_AUTHOR / APP_NAME
            config_dir = root / "config"
            cache_dir = root / "cache"
            log_dir = root / "logs"
        return cls(
            config_dir=config_dir,
            cache_dir=cache_dir,
            temp_dir=cache_dir / "tmp",
            log_dir=log_dir,
            settings_file=config_dir / "settings.json",
        )

    @classmethod
    def under(cls, root: Path) -> AppPaths:
        return cls(
            config_dir=root / "config",
            cache_dir=root / "cache",
            temp_dir=root / "cache" / "tmp",
            log_dir=root / "logs",
            settings_file=root / "config" / "settings.json",
        )

    def ensure(self) -> AppPaths:
        for directory in (self.config_dir, self.cache_dir, self.temp_dir, self.log_dir):
            directory.mkdir(parents=True, exist_ok=True)
        return self
