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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(18)

        title = QLabel("QuickInsight Desktop")
        title.setObjectName("sectionTitle")
        subtitle = QLabel("本地、私密、面向新手的数据理解工作台")
        subtitle.setObjectName("muted")

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
            button.clicked.connect(
                lambda _checked=False, action_key=key: self.action_requested.emit(action_key)
            )
            button_grid.addWidget(button, index // 2, index % 2)
        layout.addLayout(button_grid)

        drop_zone = QFrame()
        drop_zone.setObjectName("dropZone")
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
