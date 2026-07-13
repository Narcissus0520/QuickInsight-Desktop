from __future__ import annotations

import json
import os
import zipfile
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from uuid import uuid4

import duckdb

from quick_insight import __version__
from quick_insight.application.errors import UserFacingError
from quick_insight.domain.enums import DatasetKind
from quick_insight.domain.models import DatasetHandle, TransformStep
from quick_insight.infrastructure.workspace import WorkspaceDatabase

PROJECT_SCHEMA_VERSION = 1
MANIFEST_NAME = "manifest.json"
DATABASE_NAME = "project.duckdb"
PROJECT_EXTENSION = ".qiproject"
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_PACKAGE_BYTES = 5 * 1024 * 1024 * 1024
SAMPLE_BYTES = 64 * 1024

SourceStatus = Literal["current", "metadata_changed", "missing", "mismatch", "internal"]


@dataclass(frozen=True)
class SourceFileEvidence:
    path: Path
    size: int
    modified_ns: int
    sample_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "size": self.size,
            "modified_ns": self.modified_ns,
            "sample_sha256": self.sample_sha256,
        }

    @classmethod
    def from_dict(cls, payload: object) -> SourceFileEvidence | None:
        if payload is None:
            return None
        data = _object_payload(payload, "source_evidence")
        return cls(
            path=Path(_string_payload(data.get("path"), "source_evidence.path")),
            size=_int_payload(data.get("size"), "source_evidence.size"),
            modified_ns=_int_payload(
                data.get("modified_ns"),
                "source_evidence.modified_ns",
            ),
            sample_sha256=_string_payload(
                data.get("sample_sha256"),
                "source_evidence.sample_sha256",
            ),
        )


@dataclass(frozen=True)
class ProjectDatasetEntry:
    handle: DatasetHandle
    table_name: str | None = None
    transform_steps: tuple[TransformStep, ...] = ()
    source_evidence: SourceFileEvidence | None = None

    @classmethod
    def from_handle(
        cls,
        handle: DatasetHandle,
        *,
        table_name: str | None = None,
        transform_steps: tuple[TransformStep, ...] = (),
    ) -> ProjectDatasetEntry:
        return cls(handle=handle, table_name=table_name, transform_steps=transform_steps)

    def to_dict(self) -> dict[str, object]:
        return {
            "handle": _handle_to_dict(self.handle),
            "table_name": self.table_name,
            "transform_steps": [_transform_step_to_dict(step) for step in self.transform_steps],
            "source_evidence": (
                None if self.source_evidence is None else self.source_evidence.to_dict()
            ),
        }

    @classmethod
    def from_dict(cls, payload: object) -> ProjectDatasetEntry:
        data = _object_payload(payload, "dataset")
        return cls(
            handle=_handle_from_dict(data.get("handle")),
            table_name=_optional_string(data.get("table_name")),
            transform_steps=tuple(
                _transform_step_from_dict(item)
                for item in _list_payload(data.get("transform_steps", ()), "transform_steps")
            ),
            source_evidence=SourceFileEvidence.from_dict(data.get("source_evidence")),
        )


@dataclass(frozen=True)
class ProjectManifest:
    project_id: str
    display_name: str
    datasets: tuple[ProjectDatasetEntry, ...]
    created_at: datetime
    saved_at: datetime
    schema_version: int = PROJECT_SCHEMA_VERSION
    app_version: str = __version__

    @classmethod
    def create(
        cls,
        display_name: str,
        datasets: tuple[ProjectDatasetEntry, ...],
    ) -> ProjectManifest:
        now = datetime.now(UTC)
        return cls(
            project_id=f"project_{uuid4().hex}",
            display_name=display_name.strip() or "未命名项目",
            datasets=datasets,
            created_at=now,
            saved_at=now,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "app_version": self.app_version,
            "project_id": self.project_id,
            "display_name": self.display_name,
            "created_at": self.created_at.isoformat(),
            "saved_at": self.saved_at.isoformat(),
            "datasets": [dataset.to_dict() for dataset in self.datasets],
        }

    @classmethod
    def from_dict(cls, payload: object) -> ProjectManifest:
        data = _object_payload(payload, "manifest")
        schema_version = _int_payload(data.get("schema_version"), "schema_version")
        if schema_version != PROJECT_SCHEMA_VERSION:
            raise UserFacingError(
                code="PROJECT_SCHEMA_UNSUPPORTED",
                title_zh="项目版本不受支持",
                message_zh=f"当前项目格式版本为 {schema_version}，应用支持版本为 1。",
                next_action_zh="请使用匹配版本的快析桌面版打开该项目。",
                technical_detail=f"schema_version={schema_version}",
            )
        return cls(
            project_id=_string_payload(data.get("project_id"), "project_id"),
            display_name=_string_payload(data.get("display_name"), "display_name"),
            datasets=tuple(
                ProjectDatasetEntry.from_dict(item)
                for item in _list_payload(data.get("datasets"), "datasets")
            ),
            created_at=_datetime_payload(data.get("created_at"), "created_at"),
            saved_at=_datetime_payload(data.get("saved_at"), "saved_at"),
            schema_version=schema_version,
            app_version=_string_payload(data.get("app_version"), "app_version"),
        )


@dataclass(frozen=True)
class SourceReferenceStatus:
    dataset_id: str
    display_name: str
    status: SourceStatus
    source_path: Path | None
    message_zh: str
    expected: SourceFileEvidence | None = None
    actual: SourceFileEvidence | None = None


@dataclass(frozen=True)
class ProjectSaveResult:
    path: Path
    manifest: ProjectManifest
    workspace_bytes: int


@dataclass(frozen=True)
class ProjectOpenResult:
    path: Path
    manifest: ProjectManifest
    workspace: WorkspaceDatabase
    source_statuses: tuple[SourceReferenceStatus, ...]


@dataclass(frozen=True)
class ProjectRelocationResult:
    manifest: ProjectManifest
    status: SourceReferenceStatus


class ProjectPersistenceService:
    def __init__(self, workspace: WorkspaceDatabase) -> None:
        self._workspace = workspace

    def save_project(
        self,
        destination: Path,
        manifest: ProjectManifest,
    ) -> ProjectSaveResult:
        destination = _project_path(destination)
        if not self._workspace.path.exists():
            raise UserFacingError(
                code="PROJECT_WORKSPACE_NOT_FOUND",
                title_zh="没有可保存的工作区",
                message_zh="当前本地 DuckDB 工作区文件不存在，无法保存项目。",
                next_action_zh="请先导入或录入数据后再保存项目。",
                technical_detail=str(self._workspace.path),
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        manifest_to_save = _refresh_manifest_for_save(manifest)
        manifest_to_save = replace(
            manifest_to_save,
            datasets=tuple(
                _refresh_dataset_source_evidence(dataset)
                for dataset in manifest_to_save.datasets
            ),
        )
        temp_path = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
        try:
            _checkpoint_duckdb(self._workspace.path)
            workspace_bytes = self._workspace.path.stat().st_size
            with zipfile.ZipFile(
                temp_path,
                mode="w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=6,
            ) as archive:
                archive.writestr(
                    MANIFEST_NAME,
                    json.dumps(
                        manifest_to_save.to_dict(),
                        ensure_ascii=False,
                        sort_keys=True,
                        indent=2,
                    ),
                )
                archive.write(self._workspace.path, DATABASE_NAME)
            os.replace(temp_path, destination)
        except UserFacingError:
            temp_path.unlink(missing_ok=True)
            raise
        except Exception as exc:
            temp_path.unlink(missing_ok=True)
            raise UserFacingError(
                code="PROJECT_SAVE_FAILED",
                title_zh="项目保存失败",
                message_zh="写入 .qiproject 项目包时发生错误。",
                next_action_zh="请检查目标文件夹权限和磁盘空间后重试。",
                technical_detail=repr(exc),
            ) from exc
        return ProjectSaveResult(
            path=destination,
            manifest=manifest_to_save,
            workspace_bytes=workspace_bytes,
        )

    def open_project(self, project_path: Path, workspace_path: Path) -> ProjectOpenResult:
        project_path = project_path.expanduser().resolve()
        workspace_path = workspace_path.expanduser().resolve()
        if not project_path.exists() or not project_path.is_file():
            raise UserFacingError(
                code="PROJECT_FILE_NOT_FOUND",
                title_zh="找不到项目文件",
                message_zh="请选择一个存在的 .qiproject 文件。",
                next_action_zh="检查项目文件路径后重新打开。",
                technical_detail=str(project_path),
            )
        workspace_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = workspace_path.with_name(f".{workspace_path.name}.{uuid4().hex}.tmp")
        try:
            with zipfile.ZipFile(project_path) as archive:
                _validate_project_archive(archive)
                manifest = _read_manifest_from_archive(archive)
                _copy_workspace_from_archive(archive, temp_path)
            os.replace(temp_path, workspace_path)
            _validate_restored_workspace(workspace_path)
        except UserFacingError:
            temp_path.unlink(missing_ok=True)
            raise
        except Exception as exc:
            temp_path.unlink(missing_ok=True)
            raise UserFacingError(
                code="PROJECT_OPEN_FAILED",
                title_zh="项目打开失败",
                message_zh="读取 .qiproject 项目包时发生错误。",
                next_action_zh="请确认项目文件完整且未被其他程序占用。",
                technical_detail=repr(exc),
            ) from exc
        workspace = WorkspaceDatabase(workspace_path)
        return ProjectOpenResult(
            path=project_path,
            manifest=manifest,
            workspace=workspace,
            source_statuses=validate_source_references(manifest),
        )


def validate_source_references(
    manifest: ProjectManifest,
) -> tuple[SourceReferenceStatus, ...]:
    return tuple(_source_status_for_dataset(dataset) for dataset in manifest.datasets)


def relocate_source_reference(
    manifest: ProjectManifest,
    *,
    dataset_id: str,
    new_source_path: Path,
) -> ProjectRelocationResult:
    resolved_source = new_source_path.expanduser().resolve()
    if not resolved_source.exists() or not resolved_source.is_file():
        raise UserFacingError(
            code="PROJECT_RELOCATION_SOURCE_NOT_FOUND",
            title_zh="找不到重定位源文件",
            message_zh="请选择一个存在的源文件。",
            next_action_zh="检查文件路径后重新选择。",
            technical_detail=str(resolved_source),
        )
    datasets = list(manifest.datasets)
    for index, dataset in enumerate(datasets):
        if dataset.handle.id != dataset_id:
            continue
        expected = dataset.source_evidence
        if expected is None:
            raise UserFacingError(
                code="PROJECT_RELOCATION_NO_EVIDENCE",
                title_zh="缺少源文件校验证据",
                message_zh="该数据集没有保存可用于重定位的源文件证据。",
                next_action_zh="请重新导入该源文件，或选择另一个有源文件证据的数据集。",
                technical_detail=f"dataset_id={dataset_id}",
            )
        actual = source_file_evidence(resolved_source)
        if expected.size != actual.size or expected.sample_sha256 != actual.sample_sha256:
            raise UserFacingError(
                code="PROJECT_RELOCATION_MISMATCH",
                title_zh="源文件不匹配",
                message_zh="所选文件的大小或内容采样与项目记录不一致，已拒绝绑定。",
                next_action_zh="请选择原始源文件，或确认数据后重新导入。",
                technical_detail=(
                    f"dataset_id={dataset_id}; expected_size={expected.size}; "
                    f"actual_size={actual.size}; expected_sample={expected.sample_sha256}; "
                    f"actual_sample={actual.sample_sha256}"
                ),
            )
        relocated_handle = replace(dataset.handle, source_path=resolved_source)
        relocated_dataset = replace(
            dataset,
            handle=relocated_handle,
            source_evidence=actual,
        )
        datasets[index] = relocated_dataset
        relocated_manifest = replace(manifest, datasets=tuple(datasets))
        return ProjectRelocationResult(
            manifest=relocated_manifest,
            status=_source_status_for_dataset(relocated_dataset),
        )
    raise UserFacingError(
        code="PROJECT_DATASET_NOT_FOUND",
        title_zh="找不到数据集",
        message_zh="项目中没有找到需要重定位的数据集。",
        next_action_zh="请刷新项目后再尝试重定位。",
        technical_detail=f"dataset_id={dataset_id}",
    )


def source_file_evidence(path: Path) -> SourceFileEvidence:
    source = path.expanduser().resolve()
    stat = source.stat()
    digest = sha256()
    with source.open("rb") as stream:
        digest.update(stream.read(SAMPLE_BYTES))
        if stat.st_size > SAMPLE_BYTES:
            stream.seek(max(0, stat.st_size - SAMPLE_BYTES))
            digest.update(stream.read(SAMPLE_BYTES))
    return SourceFileEvidence(
        path=source,
        size=stat.st_size,
        modified_ns=stat.st_mtime_ns,
        sample_sha256=digest.hexdigest(),
    )


def _project_path(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if resolved.suffix.lower() != PROJECT_EXTENSION:
        resolved = resolved.with_suffix(PROJECT_EXTENSION)
    return resolved


def _checkpoint_duckdb(path: Path) -> None:
    try:
        with duckdb.connect(str(path)) as connection:
            connection.execute("CHECKPOINT")
    except Exception as exc:
        raise UserFacingError(
            code="PROJECT_WORKSPACE_CHECKPOINT_FAILED",
            title_zh="工作区整理失败",
            message_zh="保存项目之前无法整理本地 DuckDB 工作区。",
            next_action_zh="请稍后重试；如果仍失败，请关闭正在运行的查询后再保存。",
            technical_detail=repr(exc),
        ) from exc


def _validate_restored_workspace(path: Path) -> None:
    try:
        with duckdb.connect(str(path)) as connection:
            connection.execute("SELECT 1").fetchone()
    except Exception as exc:
        raise UserFacingError(
            code="PROJECT_DATABASE_INVALID",
            title_zh="项目数据库无效",
            message_zh="项目包中的 project.duckdb 无法作为 DuckDB 工作区打开。",
            next_action_zh="请重新选择项目文件，或从备份恢复。",
            technical_detail=repr(exc),
        ) from exc


def _refresh_manifest_for_save(manifest: ProjectManifest) -> ProjectManifest:
    return replace(manifest, saved_at=datetime.now(UTC))


def _refresh_dataset_source_evidence(dataset: ProjectDatasetEntry) -> ProjectDatasetEntry:
    source_path = dataset.handle.source_path
    if source_path is None:
        return replace(dataset, source_evidence=None)
    evidence: SourceFileEvidence | None
    try:
        evidence = source_file_evidence(source_path)
    except OSError:
        evidence = dataset.source_evidence
    return replace(dataset, source_evidence=evidence)


def _source_status_for_dataset(dataset: ProjectDatasetEntry) -> SourceReferenceStatus:
    handle = dataset.handle
    source_path = handle.source_path
    if source_path is None:
        return SourceReferenceStatus(
            dataset_id=handle.id,
            display_name=handle.display_name,
            status="internal",
            source_path=None,
            message_zh="内部数据已完整保存在项目中，不需要外部源文件。",
            expected=dataset.source_evidence,
            actual=None,
        )
    if not source_path.exists() or not source_path.is_file():
        return SourceReferenceStatus(
            dataset_id=handle.id,
            display_name=handle.display_name,
            status="missing",
            source_path=source_path,
            message_zh="源文件缺失，需要用户重定位后再验证。",
            expected=dataset.source_evidence,
            actual=None,
        )
    actual = source_file_evidence(source_path)
    expected = dataset.source_evidence
    if expected is None:
        return SourceReferenceStatus(
            dataset_id=handle.id,
            display_name=handle.display_name,
            status="metadata_changed",
            source_path=source_path,
            message_zh="源文件存在，但项目没有旧证据可比对；建议重新保存项目。",
            expected=None,
            actual=actual,
        )
    if expected.size != actual.size or expected.sample_sha256 != actual.sample_sha256:
        return SourceReferenceStatus(
            dataset_id=handle.id,
            display_name=handle.display_name,
            status="mismatch",
            source_path=source_path,
            message_zh="源文件大小或内容采样不匹配，请勿自动绑定。",
            expected=expected,
            actual=actual,
        )
    if expected.modified_ns != actual.modified_ns:
        return SourceReferenceStatus(
            dataset_id=handle.id,
            display_name=handle.display_name,
            status="metadata_changed",
            source_path=source_path,
            message_zh="源文件内容采样匹配，但修改时间不同；建议用户确认后重新保存。",
            expected=expected,
            actual=actual,
        )
    return SourceReferenceStatus(
        dataset_id=handle.id,
        display_name=handle.display_name,
        status="current",
        source_path=source_path,
        message_zh="源文件存在且与项目记录一致。",
        expected=expected,
        actual=actual,
    )


def _validate_project_archive(archive: zipfile.ZipFile) -> None:
    names = {info.filename for info in archive.infolist()}
    if MANIFEST_NAME not in names or DATABASE_NAME not in names:
        raise UserFacingError(
            code="PROJECT_ARCHIVE_INCOMPLETE",
            title_zh="项目文件不完整",
            message_zh=".qiproject 包缺少 manifest.json 或 project.duckdb。",
            next_action_zh="请重新选择完整的项目文件。",
            technical_detail=f"members={sorted(names)}",
        )
    total_size = 0
    for info in archive.infolist():
        _validate_archive_member(info)
        total_size += info.file_size
        if info.filename == MANIFEST_NAME and info.file_size > MAX_MANIFEST_BYTES:
            raise UserFacingError(
                code="PROJECT_MANIFEST_TOO_LARGE",
                title_zh="项目清单过大",
                message_zh="manifest.json 超过安全读取上限。",
                next_action_zh="请确认项目文件来源可信并重新导出。",
                technical_detail=f"manifest_size={info.file_size}",
            )
    if total_size > MAX_PACKAGE_BYTES:
        raise UserFacingError(
            code="PROJECT_ARCHIVE_TOO_LARGE",
            title_zh="项目文件过大",
            message_zh=".qiproject 解包后的总大小超过安全上限。",
            next_action_zh="请清理项目缓存或联系维护者处理。",
            technical_detail=f"total_size={total_size}",
        )


def _validate_archive_member(info: zipfile.ZipInfo) -> None:
    name = info.filename.replace("\\", "/")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or not name or name.startswith("/"):
        raise UserFacingError(
            code="PROJECT_ARCHIVE_UNSAFE_PATH",
            title_zh="项目文件路径不安全",
            message_zh=".qiproject 包含可能越权写入的路径，已拒绝打开。",
            next_action_zh="请只打开由快析桌面版生成的项目文件。",
            technical_detail=info.filename,
        )
    if info.is_dir():
        return


def _read_manifest_from_archive(archive: zipfile.ZipFile) -> ProjectManifest:
    with archive.open(MANIFEST_NAME) as stream:
        raw = stream.read(MAX_MANIFEST_BYTES + 1)
    if len(raw) > MAX_MANIFEST_BYTES:
        raise UserFacingError(
            code="PROJECT_MANIFEST_TOO_LARGE",
            title_zh="项目清单过大",
            message_zh="manifest.json 超过安全读取上限。",
            next_action_zh="请确认项目文件来源可信并重新导出。",
            technical_detail=f"manifest_size>{MAX_MANIFEST_BYTES}",
        )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UserFacingError(
            code="PROJECT_MANIFEST_INVALID",
            title_zh="项目清单无效",
            message_zh="manifest.json 不是有效的 UTF-8 JSON。",
            next_action_zh="请重新选择项目文件，或从备份恢复。",
            technical_detail=str(exc),
        ) from exc
    return ProjectManifest.from_dict(payload)


def _copy_workspace_from_archive(archive: zipfile.ZipFile, destination: Path) -> None:
    with archive.open(DATABASE_NAME) as source, destination.open("wb") as target:
        copied = 0
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            copied += len(chunk)
            if copied > MAX_PACKAGE_BYTES:
                raise UserFacingError(
                    code="PROJECT_DATABASE_TOO_LARGE",
                    title_zh="项目数据库过大",
                    message_zh="project.duckdb 超过安全读取上限。",
                    next_action_zh="请清理项目缓存或联系维护者处理。",
                    technical_detail=f"copied={copied}",
                )
            target.write(chunk)


def _handle_to_dict(handle: DatasetHandle) -> dict[str, object]:
    return {
        "id": handle.id,
        "kind": handle.kind.value,
        "display_name": handle.display_name,
        "schema_version": handle.schema_version,
        "source_path": None if handle.source_path is None else str(handle.source_path),
        "workspace_path": None if handle.workspace_path is None else str(handle.workspace_path),
        "row_count": handle.row_count,
        "column_count": handle.column_count,
        "import_options": _json_safe_object(handle.import_options),
        "fingerprint": handle.fingerprint,
        "cache_key": handle.cache_key,
    }


def _handle_from_dict(payload: object) -> DatasetHandle:
    data = _object_payload(payload, "handle")
    return DatasetHandle(
        id=_string_payload(data.get("id"), "handle.id"),
        kind=DatasetKind(_string_payload(data.get("kind"), "handle.kind")),
        display_name=_string_payload(data.get("display_name"), "handle.display_name"),
        schema_version=_int_payload(data.get("schema_version", 1), "handle.schema_version"),
        source_path=_optional_path(data.get("source_path")),
        workspace_path=_optional_path(data.get("workspace_path")),
        row_count=_optional_int(data.get("row_count")),
        column_count=_optional_int(data.get("column_count")),
        import_options=_object_payload(data.get("import_options", {}), "import_options"),
        fingerprint=_optional_string(data.get("fingerprint")),
        cache_key=_optional_string(data.get("cache_key")),
    )


def _transform_step_to_dict(step: TransformStep) -> dict[str, object]:
    return {
        "id": step.id,
        "operation": step.operation,
        "parameters": _json_safe_object(step.parameters),
        "reversible": step.reversible,
        "schema_version": step.schema_version,
    }


def _transform_step_from_dict(payload: object) -> TransformStep:
    data = _object_payload(payload, "transform_step")
    reversible = data.get("reversible")
    if not isinstance(reversible, bool):
        raise ValueError("transform_step.reversible must be a boolean.")
    return TransformStep(
        id=_string_payload(data.get("id"), "transform_step.id"),
        operation=_string_payload(data.get("operation"), "transform_step.operation"),
        parameters=_object_payload(data.get("parameters"), "transform_step.parameters"),
        reversible=reversible,
        schema_version=_int_payload(
            data.get("schema_version", 1),
            "transform_step.schema_version",
        ),
    )


def _json_safe_object(payload: dict[str, Any]) -> dict[str, object]:
    return {str(key): _json_safe_value(value) for key, value in payload.items()}


def _json_safe_value(value: object) -> object:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def _object_payload(payload: object, name: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError(f"{name} must be an object.")
    return {str(key): value for key, value in payload.items()}


def _list_payload(payload: object, name: str) -> list[object]:
    if not isinstance(payload, list | tuple):
        raise ValueError(f"{name} must be a list.")
    return list(payload)


def _string_payload(payload: object, name: str) -> str:
    if not isinstance(payload, str) or not payload:
        raise ValueError(f"{name} must be a non-empty string.")
    return payload


def _int_payload(payload: object, name: str) -> int:
    if not isinstance(payload, int):
        raise ValueError(f"{name} must be an integer.")
    return payload


def _datetime_payload(payload: object, name: str) -> datetime:
    text = _string_payload(payload, name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{name} must be ISO datetime.") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _optional_string(payload: object) -> str | None:
    return payload if isinstance(payload, str) and payload else None


def _optional_path(payload: object) -> Path | None:
    text = _optional_string(payload)
    return None if text is None else Path(text)


def _optional_int(payload: object) -> int | None:
    if payload is None:
        return None
    if not isinstance(payload, int):
        raise ValueError("Expected optional integer.")
    return payload
