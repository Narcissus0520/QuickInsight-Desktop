from __future__ import annotations

import json
import zipfile

import pytest

from quick_insight.application.errors import UserFacingError
from quick_insight.application.importing import TabularImportService
from quick_insight.application.project import (
    DATABASE_NAME,
    MANIFEST_NAME,
    ProjectDatasetEntry,
    ProjectManifest,
    ProjectPersistenceService,
    relocate_source_reference,
    validate_source_references,
)
from quick_insight.application.text_corpus import TextCorpusService
from quick_insight.infrastructure.workspace import WorkspaceDatabase


def test_qiproject_save_and_open_restores_workspace_and_manifest(tmp_path) -> None:  # type: ignore[no-untyped-def]
    source = tmp_path / "sales.csv"
    source.write_text("region,amount\nNorth,10\nSouth,20\n", encoding="utf-8")
    workspace = WorkspaceDatabase(tmp_path / "workspace.duckdb")
    tabular_result = TabularImportService(workspace).import_csv(
        TabularImportService(workspace).preview_csv(source)
    )
    text_result = TextCorpusService(workspace).import_preview(
        TextCorpusService(workspace).preview_text(
            "第一条反馈\n第二条反馈",
            display_name="手动语料",
        )
    )
    manifest = ProjectManifest.create(
        "持久化测试项目",
        (
            ProjectDatasetEntry.from_handle(
                tabular_result.handle,
                table_name=tabular_result.table_name,
            ),
            ProjectDatasetEntry.from_handle(text_result.handle),
        ),
    )
    project_path = tmp_path / "analysis.qiproject"

    save_result = ProjectPersistenceService(workspace).save_project(project_path, manifest)
    opened = ProjectPersistenceService(WorkspaceDatabase(tmp_path / "unused.duckdb")).open_project(
        project_path,
        tmp_path / "reopened.duckdb",
    )

    assert save_result.path == project_path
    assert save_result.workspace_bytes > 0
    assert project_path.exists()
    with zipfile.ZipFile(project_path) as archive:
        assert {MANIFEST_NAME, DATABASE_NAME}.issubset(set(archive.namelist()))
        manifest_payload = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
    assert manifest_payload["schema_version"] == 1
    assert opened.manifest.display_name == "持久化测试项目"
    assert opened.workspace.row_count(tabular_result.table_name) == 2
    assert opened.workspace.fetch_page(tabular_result.table_name, limit=2, offset=0) == (
        ("North", 10),
        ("South", 20),
    )
    assert len(opened.workspace.list_text_records(text_result.handle.cache_key or "")) == 2
    statuses = {status.dataset_id: status.status for status in opened.source_statuses}
    assert statuses[tabular_result.handle.id] == "current"
    assert statuses[text_result.handle.id] == "internal"


def test_qiproject_source_relocation_requires_matching_source_evidence(tmp_path) -> None:  # type: ignore[no-untyped-def]
    source = tmp_path / "sales.csv"
    source.write_text("region,amount\nNorth,10\n", encoding="utf-8")
    workspace = WorkspaceDatabase(tmp_path / "workspace.duckdb")
    service = TabularImportService(workspace)
    tabular_result = service.import_csv(service.preview_csv(source))
    manifest = ProjectManifest.create(
        "重定位测试",
        (
            ProjectDatasetEntry.from_handle(
                tabular_result.handle,
                table_name=tabular_result.table_name,
            ),
        ),
    )
    project_path = tmp_path / "relocation.qiproject"
    ProjectPersistenceService(workspace).save_project(project_path, manifest)
    relocated_source = tmp_path / "moved" / "sales.csv"
    relocated_source.parent.mkdir()
    source.rename(relocated_source)
    opened = ProjectPersistenceService(WorkspaceDatabase(tmp_path / "unused.duckdb")).open_project(
        project_path,
        tmp_path / "reopened.duckdb",
    )

    assert validate_source_references(opened.manifest)[0].status == "missing"
    relocation = relocate_source_reference(
        opened.manifest,
        dataset_id=tabular_result.handle.id,
        new_source_path=relocated_source,
    )

    assert relocation.status.status == "current"
    relocated_dataset = relocation.manifest.datasets[0]
    assert relocated_dataset.handle.source_path == relocated_source.resolve()
    assert validate_source_references(relocation.manifest)[0].status == "current"

    wrong_source = tmp_path / "wrong.csv"
    wrong_source.write_text("region,amount\nNorth,999\n", encoding="utf-8")
    with pytest.raises(UserFacingError) as exc_info:
        relocate_source_reference(
            opened.manifest,
            dataset_id=tabular_result.handle.id,
            new_source_path=wrong_source,
        )
    assert exc_info.value.code == "PROJECT_RELOCATION_MISMATCH"


def test_qiproject_open_rejects_unsafe_archive_paths(tmp_path) -> None:  # type: ignore[no-untyped-def]
    project_path = tmp_path / "unsafe.qiproject"
    manifest = ProjectManifest.create("unsafe", ())
    with zipfile.ZipFile(project_path, "w") as archive:
        archive.writestr(MANIFEST_NAME, json.dumps(manifest.to_dict()))
        archive.writestr(DATABASE_NAME, b"not a real database")
        archive.writestr("../evil.txt", b"bad")

    with pytest.raises(UserFacingError) as exc_info:
        ProjectPersistenceService(WorkspaceDatabase(tmp_path / "unused.duckdb")).open_project(
            project_path,
            tmp_path / "reopened.duckdb",
        )

    assert exc_info.value.code == "PROJECT_ARCHIVE_UNSAFE_PATH"
    assert not (tmp_path / "evil.txt").exists()
