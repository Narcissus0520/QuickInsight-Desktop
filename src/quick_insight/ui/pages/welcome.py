from __future__ import annotations

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from quick_insight.ui.accessibility import describe_widget, ensure_hit_target


class WelcomePage(QWidget):
    action_requested = Signal(str)
    file_dropped = Signal(str)

    ACTIONS: tuple[tuple[str, str, bool], ...] = (
        ("导入表格数据", "import_tabular", True),
        ("录入文本语句", "create_text_corpus", False),
        ("打开最近项目", "open_recent", False),
        ("打开示例数据", "open_sample", False),
    )

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("welcomePage")
        self.setAcceptDrops(True)
        describe_widget(
            self,
            name="欢迎页",
            description="提供表格导入、文本录入、最近项目、示例数据和拖放入口。",
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(18)

        title = QLabel("QuickInsight Desktop")
        title.setObjectName("sectionTitle")
        describe_widget(title, name="欢迎页标题")
        subtitle = QLabel("本地、私密、面向新手的数据理解工作台")
        subtitle.setObjectName("muted")
        describe_widget(subtitle, name="欢迎页说明")

        layout.addWidget(title)
        layout.addWidget(subtitle)

        button_grid = QGridLayout()
        button_grid.setHorizontalSpacing(12)
        button_grid.setVerticalSpacing(12)
        for index, (text, key, primary) in enumerate(self.ACTIONS):
            button = QPushButton(text)
            button.setObjectName(f"welcomeAction_{key}")
            button.setProperty("primary", primary)
            button.setMinimumHeight(44)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            describe_widget(
                button,
                name=text,
                description=_action_description(key),
                tooltip=_action_description(key),
            )
            ensure_hit_target(button, min_width=160, min_height=44)
            button.clicked.connect(
                lambda _checked=False, action_key=key: self.action_requested.emit(action_key)
            )
            button_grid.addWidget(button, index // 2, index % 2)
        layout.addLayout(button_grid)

        drop_zone = QFrame()
        drop_zone.setObjectName("dropZone")
        describe_widget(
            drop_zone,
            name="文件拖放区",
            description="把本地表格文件拖到这里以进入导入预览。",
        )
        drop_layout = QVBoxLayout(drop_zone)
        drop_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop_title = QLabel("拖放文件到这里")
        drop_title.setObjectName("sectionTitle")
        drop_hint = QLabel("拖放表格文件可导入预览；文本语句请点击“录入文本语句”。")
        drop_hint.setObjectName("muted")
        drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop_layout.addWidget(drop_title, alignment=Qt.AlignmentFlag.AlignCenter)
        drop_layout.addWidget(drop_hint, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(drop_zone)
        layout.addStretch(1)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if _first_local_file(event.mimeData()) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        path = _first_local_file(event.mimeData())
        if path is None:
            event.ignore()
            return
        self.file_dropped.emit(path)
        event.acceptProposedAction()


def _first_local_file(mime_data: QMimeData) -> str | None:
    for url in mime_data.urls():
        if url.isLocalFile():
            return url.toLocalFile()
    return None


def _action_description(action_key: str) -> str:
    return {
        "import_tabular": "选择 CSV、TSV、Excel 或 Parquet 文件并进入导入预览。",
        "create_text_corpus": "录入或粘贴文本语句并创建文本语料。",
        "open_recent": "打开最近使用的 QuickInsight 项目。当前为后续里程碑入口。",
        "open_sample": "打开内置示例数据。当前为后续里程碑入口。",
    }.get(action_key, "执行欢迎页操作。")
