from __future__ import annotations

import ast
import json
import os
import platform
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from quick_insight import __version__

BANNED_CALLS = frozenset({"eval", "exec", "compile"})
BANNED_IMPORTS = frozenset(
    {
        "httpx",
        "marshal",
        "pickle",
        "requests",
        "shelve",
        "urllib.request",
        "yaml",
    }
)
REMOTE_LITERAL_PREFIXES = tuple(f"{scheme}://" for scheme in ("http", "https", "ws", "wss"))
UNSAFE_ARCHIVE_METHODS = frozenset({"extract", "extractall"})


@dataclass(frozen=True)
class SecurityFinding:
    rule_id: str
    severity: str
    path: Path
    line: int
    message: str

    def to_dict(self, root: Path) -> dict[str, object]:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "path": str(self.path.relative_to(root)),
            "line": self.line,
            "message": self.message,
        }


@dataclass(frozen=True)
class SecurityReviewResult:
    generated_at: datetime
    root: Path
    scanned_files: tuple[Path, ...]
    findings: tuple[SecurityFinding, ...]
    schema_version: int = 1

    @property
    def passed(self) -> bool:
        return not self.findings

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at.isoformat(),
            "app_version": __version__,
            "machine": _machine_details(),
            "root": str(self.root),
            "scanned_files": [str(path.relative_to(self.root)) for path in self.scanned_files],
            "findings": [finding.to_dict(self.root) for finding in self.findings],
            "passed": self.passed,
            "rules": {
                "banned_calls": sorted(BANNED_CALLS),
                "banned_imports": sorted(BANNED_IMPORTS),
                "remote_literal_prefixes": list(REMOTE_LITERAL_PREFIXES),
                "unsafe_archive_methods": sorted(UNSAFE_ARCHIVE_METHODS),
                "subprocess_shell_true": True,
            },
        }


def run_security_review(root: Path) -> SecurityReviewResult:
    resolved_root = root.resolve()
    python_files = tuple(sorted((resolved_root / "src").rglob("*.py")))
    findings: list[SecurityFinding] = []
    for path in python_files:
        findings.extend(_scan_python_file(resolved_root, path))
    return SecurityReviewResult(
        generated_at=datetime.now(UTC),
        root=resolved_root,
        scanned_files=python_files,
        findings=tuple(
            sorted(findings, key=lambda item: (str(item.path), item.line, item.rule_id))
        ),
    )


def write_security_review_reports(
    result: SecurityReviewResult,
    output_dir: Path,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = result.generated_at.strftime("%Y%m%dT%H%M%SZ")
    json_path = output_dir / f"security-review-{timestamp}.json"
    markdown_path = output_dir / f"security-review-{timestamp}.md"
    json_path.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(_security_review_markdown(result), encoding="utf-8")
    return json_path, markdown_path


def _scan_python_file(root: Path, path: Path) -> tuple[SecurityFinding, ...]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        return (
            SecurityFinding(
                rule_id="python_syntax_error",
                severity="error",
                path=path,
                line=exc.lineno or 1,
                message=str(exc),
            ),
        )
    visitor = _SecurityAstVisitor(root=root, path=path)
    visitor.visit(tree)
    return tuple(visitor.findings)


class _SecurityAstVisitor(ast.NodeVisitor):
    def __init__(self, *, root: Path, path: Path) -> None:
        self.root = root
        self.path = path
        self.findings: list[SecurityFinding] = []

    def visit_Call(self, node: ast.Call) -> None:
        function = node.func
        if isinstance(function, ast.Name) and function.id in BANNED_CALLS:
            self._add(
                "banned_dynamic_execution",
                node,
                f"Do not call {function.id}; QuickInsight forbids dynamic code execution.",
            )
        if _is_subprocess_shell_true(function, node):
            self._add(
                "subprocess_shell_true",
                node,
                "Do not run subprocesses with shell=True.",
            )
        if isinstance(function, ast.Attribute) and function.attr in UNSAFE_ARCHIVE_METHODS:
            self._add(
                "unsafe_archive_extraction",
                node,
                f"Do not call archive.{function.attr}; stream validated members explicitly.",
            )
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if _is_banned_import(alias.name):
                self._add(
                    "banned_import",
                    node,
                    (
                        f"Do not import {alias.name}; it violates the "
                        "offline/safe-deserialization policy."
                    ),
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        if _is_banned_import(module):
            self._add(
                "banned_import",
                node,
                (
                    f"Do not import from {module}; it violates the "
                    "offline/safe-deserialization policy."
                ),
            )
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str):
            text = node.value.strip().casefold()
            if text.startswith(REMOTE_LITERAL_PREFIXES):
                self._add(
                    "remote_url_literal",
                    node,
                    "Production code must not embed remote URLs or remote assets.",
                )
        self.generic_visit(node)

    def _add(self, rule_id: str, node: ast.AST, message: str) -> None:
        self.findings.append(
            SecurityFinding(
                rule_id=rule_id,
                severity="error",
                path=self.path,
                line=getattr(node, "lineno", 1),
                message=message,
            )
        )


def _is_subprocess_shell_true(function: ast.expr, node: ast.Call) -> bool:
    if not (
        isinstance(function, ast.Attribute)
        and function.attr in {"call", "check_call", "check_output", "run", "Popen"}
        and isinstance(function.value, ast.Name)
        and function.value.id == "subprocess"
    ):
        return False
    for keyword in node.keywords:
        if keyword.arg == "shell" and isinstance(keyword.value, ast.Constant):
            return keyword.value.value is True
    return False


def _is_banned_import(name: str) -> bool:
    normalized = name.casefold()
    return normalized in BANNED_IMPORTS or any(
        normalized.startswith(f"{banned}.") for banned in BANNED_IMPORTS
    )


def _machine_details() -> dict[str, object]:
    return {
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "machine": platform.machine(),
        "logical_cpu_count": os.cpu_count() or 0,
    }


def _security_review_markdown(result: SecurityReviewResult) -> str:
    lines = [
        "# QuickInsight Security Review",
        "",
        f"Generated: {result.generated_at.isoformat()}",
        f"App version: {__version__}",
        f"Scanned files: {len(result.scanned_files)}",
        f"Passed: {result.passed}",
        "",
        "## Rules",
        "",
        "- No dynamic code execution through eval, exec, or compile.",
        "- No unsafe deserialization/network-client imports.",
        "- No subprocess shell execution.",
        "- No direct ZIP extract/extractall calls.",
        "- No remote URL literals in production code.",
        "",
    ]
    if not result.findings:
        lines.append("No findings.")
        lines.append("")
        return "\n".join(lines)
    lines.extend(["## Findings", ""])
    for finding in result.findings:
        lines.append(
            "- "
            f"`{finding.rule_id}` {finding.path.relative_to(result.root)}:{finding.line} - "
            f"{finding.message}"
        )
    lines.append("")
    return "\n".join(lines)
