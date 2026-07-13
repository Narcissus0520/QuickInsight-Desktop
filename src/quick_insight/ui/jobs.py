from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from quick_insight.application.jobs import (
    CancellationToken,
    JobContext,
    JobOutcome,
    JobProgress,
    run_job_inline,
)


class JobSignals(QObject):
    progress = Signal(object)
    completed = Signal(object)


class QtJobRunner[T](QRunnable):
    def __init__(self, name: str, work: Callable[[JobContext], T]) -> None:
        super().__init__()
        self.name = name
        self.work = work
        self.cancellation = CancellationToken()
        self.signals = JobSignals()

    def cancel(self) -> None:
        self.cancellation.cancel()

    @Slot()
    def run(self) -> None:
        outcome: JobOutcome[T] = run_job_inline(
            self.name,
            self.work,
            cancellation=self.cancellation,
            on_progress=self._on_progress,
        )
        self.signals.completed.emit(outcome)

    def _on_progress(self, progress: JobProgress) -> None:
        self.signals.progress.emit(progress)
