from __future__ import annotations

from quick_insight.application.jobs import (
    CancellationToken,
    JobCancelled,
    JobContext,
    JobProgress,
    JobState,
    run_job_inline,
)


def test_job_reports_success_and_progress() -> None:
    events: list[JobProgress] = []

    def work(context: JobContext) -> int:
        context.progress(25, "处理中")
        return 7

    outcome = run_job_inline("sample", work, on_progress=events.append)

    assert outcome.state is JobState.SUCCEEDED
    assert outcome.value == 7
    assert [event.state for event in events] == [
        JobState.RUNNING,
        JobState.RUNNING,
        JobState.SUCCEEDED,
    ]


def test_job_reports_failure_without_raising() -> None:
    def work(_context: JobContext) -> int:
        raise RuntimeError("boom")

    outcome = run_job_inline("bad", work)

    assert outcome.state is JobState.FAILED
    assert isinstance(outcome.error, RuntimeError)


def test_job_reports_cancellation() -> None:
    token = CancellationToken()

    def work(_context: JobContext) -> int:
        token.cancel()
        raise JobCancelled

    outcome = run_job_inline("cancel", work, cancellation=token)

    assert outcome.state is JobState.CANCELLED
