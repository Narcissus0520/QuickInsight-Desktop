# Security Review

Date: 2026-07-13

## Scope

This M6 review covers production code under `src/quick_insight`, with focused checks for the current P0 threat model:

- Offline-by-default operation: no telemetry, analytics, uploads, remote assets, or network-client imports.
- No arbitrary code execution: no `eval`, `exec`, `compile`, macro execution, or shell subprocess execution.
- Safe project package handling: no direct ZIP `extract`/`extractall`; project files stream validated members only.
- Local chart rendering: Plotly HTML uses bundled local JavaScript, CSP, HTML/JSON escaping, and Qt request blocking.
- SQL safety: user-facing values flow through typed services and parameterized DuckDB queries; dynamic identifiers use controlled quoting.
- Privacy-conscious logs and audit records: runtime logs record operation metadata rather than full source rows/text.

## Automated Review

Run:

```powershell
.\scripts\security_review.ps1 -OutputDir build\security-review\reports
```

Latest result:

- Report: `build/security-review/reports/security-review-20260713T130423Z.json`
- Production files scanned: 59
- Findings: 0
- Result: pass

The automated runner checks:

- dynamic execution calls: `eval`, `exec`, `compile`
- unsafe/network-oriented imports: `pickle`, `marshal`, `shelve`, `yaml`, `requests`, `httpx`, `urllib.request`
- `subprocess` calls with `shell=True`
- direct archive `extract` / `extractall`
- remote URL literals in production code

## Manual Notes

- `.qiproject` opening validates member paths, manifest size, total uncompressed package size, and restored DuckDB readability before replacing the workspace.
- Source relocation validates saved size and head/tail sample hashes before rebinding moved source files.
- Chart WebEngine views block external network, local file, and unknown-scheme requests; tests cover the classifier and view-level recording.
- Processed exports write to temporary files and refuse to overwrite existing destinations by default.

## Remaining Security Work

The P0 security review is complete for the current code surface. Packaging hardening still needs to verify bundled Qt WebEngine resources, generated license inventory, packaged smoke launch, checksums, and release artifact contents.
