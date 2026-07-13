# Packaging

Release packaging is planned for M6.

Preferred artifacts:

- `dist/QuickInsight-Setup-x64.exe`
- `dist/QuickInsight-portable-x64.zip`
- `dist/SHA256SUMS.txt`
- `dist/release-notes.md`
- `dist/third-party-licenses/`

M0 scripts intentionally do not claim packaging success. `scripts/package.ps1` exits with a clear failure until M6 implements and validates installer/portable outputs, Qt WebEngine resources, smoke launch, checksums, and license inventory.
