from __future__ import annotations

from quick_insight.infrastructure.settings import AppSettings, load_settings, save_settings


def test_settings_round_trip_theme(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "settings.json"
    settings = AppSettings(theme="dark", recent_projects=("a.qiproject",))

    save_settings(path, settings)

    loaded = load_settings(path)
    assert loaded.theme == "dark"
    assert loaded.recent_projects == ("a.qiproject",)


def test_settings_invalid_theme_falls_back_to_light(  # type: ignore[no-untyped-def]
    tmp_path,
) -> None:
    path = tmp_path / "settings.json"
    path.write_text('{"theme": "blue"}', encoding="utf-8")

    assert load_settings(path).theme == "light"
