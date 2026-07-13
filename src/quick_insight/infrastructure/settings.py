from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal, cast

ThemeName = Literal["light", "dark"]
VALID_THEMES: frozenset[str] = frozenset({"light", "dark"})


@dataclass(frozen=True)
class AppSettings:
    theme: ThemeName = "light"
    recent_projects: tuple[str, ...] = ()
    schema_version: int = 1

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppSettings:
        raw_theme = data.get("theme", "light")
        theme: ThemeName = cast(ThemeName, raw_theme) if raw_theme in VALID_THEMES else "light"
        recent = data.get("recent_projects", [])
        if not isinstance(recent, list):
            recent = []
        return cls(
            theme=theme,
            recent_projects=tuple(str(item) for item in recent[:10]),
            schema_version=int(data.get("schema_version", 1)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "theme": self.theme,
            "recent_projects": list(self.recent_projects),
        }

    def with_theme(self, theme: str) -> AppSettings:
        if theme not in VALID_THEMES:
            return replace(self, theme="light")
        return replace(self, theme=cast(ThemeName, theme))


def load_settings(path: Path) -> AppSettings:
    if not path.exists():
        return AppSettings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return AppSettings()
    if not isinstance(data, dict):
        return AppSettings()
    return AppSettings.from_dict(data)


def save_settings(path: Path, settings: AppSettings) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(
        json.dumps(settings.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)
