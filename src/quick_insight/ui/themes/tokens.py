from __future__ import annotations

from typing import Literal

ThemeName = Literal["light", "dark"]

THEMES: dict[ThemeName, dict[str, str]] = {
    "light": {
        "bg": "#f7f8fa",
        "panel": "#ffffff",
        "panel_alt": "#eef2f5",
        "text": "#18212f",
        "muted": "#5d6b7a",
        "border": "#d8dee8",
        "accent": "#2563eb",
        "accent_text": "#ffffff",
        "danger": "#b42318",
        "status": "#edf7ef",
    },
    "dark": {
        "bg": "#171b22",
        "panel": "#202632",
        "panel_alt": "#2a3240",
        "text": "#edf2f7",
        "muted": "#a7b2c2",
        "border": "#3a4657",
        "accent": "#6aa0ff",
        "accent_text": "#0e1521",
        "danger": "#ffb4a8",
        "status": "#1d3328",
    },
}


def build_qss(theme: ThemeName) -> str:
    tokens = THEMES[theme]
    return f"""
QWidget {{
    background: {tokens["bg"]};
    color: {tokens["text"]};
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
    font-size: 13px;
}}
QMainWindow {{
    background: {tokens["bg"]};
}}
QFrame#panel, QFrame#bottomStatus, QFrame#dropZone {{
    background: {tokens["panel"]};
    border: 1px solid {tokens["border"]};
    border-radius: 6px;
}}
QFrame#recommendationCard {{
    background: {tokens["panel"]};
    border: 1px solid {tokens["border"]};
    border-radius: 6px;
}}
QFrame#dropZone {{
    background: {tokens["panel_alt"]};
    min-height: 92px;
}}
QLabel#sectionTitle {{
    color: {tokens["text"]};
    font-size: 16px;
    font-weight: 600;
}}
QLabel#recommendationTitleLabel {{
    font-size: 15px;
    font-weight: 600;
}}
QLabel#recommendationScoreLabel {{
    color: {tokens["accent"]};
    font-weight: 700;
}}
QLabel#muted, QLabel#statusMuted {{
    color: {tokens["muted"]};
}}
QLabel#errorLabel {{
    color: {tokens["danger"]};
}}
QPushButton {{
    background: {tokens["panel"]};
    border: 1px solid {tokens["border"]};
    border-radius: 6px;
    padding: 8px 12px;
}}
QPushButton:hover {{
    border-color: {tokens["accent"]};
}}
QPushButton[primary="true"] {{
    background: {tokens["accent"]};
    color: {tokens["accent_text"]};
    border-color: {tokens["accent"]};
    font-weight: 600;
}}
QListWidget, QTreeWidget, QTabWidget::pane, QTextEdit {{
    background: {tokens["panel"]};
    border: 1px solid {tokens["border"]};
    border-radius: 6px;
}}
QListWidget::item {{
    padding: 8px;
}}
QListWidget::item:selected {{
    background: {tokens["panel_alt"]};
    color: {tokens["text"]};
}}
QToolBar {{
    background: {tokens["panel"]};
    border-bottom: 1px solid {tokens["border"]};
    spacing: 8px;
}}
QStatusBar {{
    background: {tokens["panel"]};
    border-top: 1px solid {tokens["border"]};
}}
QComboBox {{
    background: {tokens["panel"]};
    border: 1px solid {tokens["border"]};
    border-radius: 6px;
    padding: 5px 8px;
}}
"""
