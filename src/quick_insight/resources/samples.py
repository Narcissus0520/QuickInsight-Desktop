from __future__ import annotations

import csv
import json
from collections.abc import Iterable
from pathlib import Path


def business_sales_rows() -> list[dict[str, str]]:
    return [
        {
            "date": "2026-01-01",
            "region": "华东",
            "product": "传感器",
            "revenue": "12800",
            "units": "32",
        },
        {
            "date": "2026-01-02",
            "region": "华南",
            "product": "控制器",
            "revenue": "9300",
            "units": "21",
        },
        {
            "date": "2026-01-03",
            "region": "华北",
            "product": "网关",
            "revenue": "15100",
            "units": "18",
        },
        {
            "date": "2026-01-04",
            "region": "华东",
            "product": "控制器",
            "revenue": "10450",
            "units": "25",
        },
        {
            "date": "2026-01-05",
            "region": "西南",
            "product": "传感器",
            "revenue": "8800",
            "units": "29",
        },
    ]


def sensor_rows() -> list[dict[str, str]]:
    return [
        {
            "timestamp": "2026-02-01T09:00:00",
            "device_id": "S-001",
            "temperature_c": "21.4",
            "vibration_mm_s": "1.2",
            "status": "ok",
        },
        {
            "timestamp": "2026-02-01T09:01:00",
            "device_id": "S-001",
            "temperature_c": "21.6",
            "vibration_mm_s": "1.3",
            "status": "ok",
        },
        {
            "timestamp": "2026-02-01T09:02:00",
            "device_id": "S-002",
            "temperature_c": "28.9",
            "vibration_mm_s": "4.8",
            "status": "warning",
        },
        {
            "timestamp": "2026-02-01T09:03:00",
            "device_id": "S-002",
            "temperature_c": "29.2",
            "vibration_mm_s": "5.1",
            "status": "warning",
        },
    ]


def dirty_rows() -> list[dict[str, str]]:
    return [
        {"id": "001", "amount": "1200", "date": "2026/03/01", "note": "ok"},
        {"id": "002", "amount": "", "date": "2026/03/02", "note": "missing amount"},
        {"id": "002", "amount": "1200", "date": "2026/03/02", "note": "duplicate id"},
        {"id": "004", "amount": "not-a-number", "date": "2026-03-04", "note": "mixed type"},
    ]


def text_records() -> list[dict[str, object]]:
    return [
        {
            "id": "t-001",
            "content": "客户反馈安装步骤太多，希望有更清楚的向导。",
            "primary_category": "产品体验",
            "tags": ["安装", "新手"],
            "source": "访谈",
        },
        {
            "id": "t-002",
            "content": "设备在高温工况下偶尔出现告警，需要核对传感器曲线。",
            "primary_category": "设备异常",
            "tags": ["传感器", "告警"],
            "source": "巡检记录",
        },
        {
            "id": "t-003",
            "content": "销售团队希望按区域快速比较本月收入。",
            "primary_category": "业务分析",
            "tags": ["收入", "区域"],
            "source": "会议纪要",
        },
    ]


def generate_samples(output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written = [
        _write_csv(output_dir / "business_sales.csv", business_sales_rows()),
        _write_csv(output_dir / "sensor_readings.csv", sensor_rows()),
        _write_csv(output_dir / "dirty_table.csv", dirty_rows()),
        _write_jsonl(output_dir / "text_corpus.jsonl", text_records()),
    ]
    return written


def _write_csv(path: Path, rows: list[dict[str, str]]) -> Path:
    if not rows:
        raise ValueError("Sample CSV requires at least one row.")
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return path


def _write_jsonl(path: Path, records: Iterable[dict[str, object]]) -> Path:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return path
