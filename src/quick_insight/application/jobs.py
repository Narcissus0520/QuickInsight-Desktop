from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum


class JobState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobCancelled(Exception):
    """Raised by cooperative jobs when cancellation is requested."""


class CancellationToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled():
            raise JobCancelled("Job was cancelled.")


@dataclass(frozen=True)
class JobProgress:
    name: str
    state: JobState
    percent: int | None = None
    message_zh: str = ""


ProgressCallback = Callable[[JobProgress], None]


@dataclass(frozen=True)
class JobContext:
    name: str
    cancellation: CancellationToken
    report_progress: ProgressCallback

    def progress(self, percent: int | None, message_zh: str) -> None:
        self.cancellation.raise_if_cancelled()
        self.report_progress(
            JobProgress(
                name=self.name,
                state=JobState.RUNNING,
                percent=percent,
                message_zh=message_zh,
            )
        )


@dataclass(frozen=True)
class JobOutcome[T]:
    name: str
    state: JobState
    value: T | None = None
    error: Exception | None = None


def run_job_inline[T](
    name: str,
    work: Callable[[JobContext], T],
    *,
    cancellation: CancellationToken | None = None,
    on_progress: ProgressCallback | None = None,
) -> JobOutcome[T]:
    token = cancellation or CancellationToken()
    progress_callback = on_progress or _ignore_progress

    def emit(state: JobState, percent: int | None, message_zh: str) -> None:
        progress_callback(
            JobProgress(name=name, state=state, percent=percent, message_zh=message_zh)
        )

    emit(JobState.RUNNING, 0, "任务已开始")
    context = JobContext(name=name, cancellation=token, report_progress=progress_callback)
    try:
        token.raise_if_cancelled()
        value = work(context)
        token.raise_if_cancelled()
    except JobCancelled:
        emit(JobState.CANCELLED, None, "任务已取消")
        return JobOutcome(name=name, state=JobState.CANCELLED)
    except Exception as exc:
        emit(JobState.FAILED, None, "任务失败")
        return JobOutcome(name=name, state=JobState.FAILED, error=exc)

    emit(JobState.SUCCEEDED, 100, "任务已完成")
    return JobOutcome(name=name, state=JobState.SUCCEEDED, value=value)


def _ignore_progress(_progress: JobProgress) -> None:
    return None
