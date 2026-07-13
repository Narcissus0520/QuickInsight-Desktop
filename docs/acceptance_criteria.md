# Acceptance Criteria

## M0 Foundation

- `scripts/setup_dev.ps1` rejects non-CPython-3.13 x64 interpreters.
- `scripts/run.ps1` launches the PySide6 shell from `.venv`.
- Welcome page and three-column workspace shell are visible.
- Light/dark theme switching works.
- Tests cover enums, settings, errors, jobs, deterministic samples, UI smoke, and no `QTableWidget` usage.
- `scripts/test.ps1` runs ruff, mypy, and pytest.
- `docs/project_status.md` records exact latest commands and results.

## Not Accepted In M0

- Data import.
- Profiling.
- Chart recommendation or rendering.
- Transform operations.
- Project save/reopen.
- Installer or portable packaging.
