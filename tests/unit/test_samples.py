from __future__ import annotations

from quick_insight.resources.samples import generate_samples


def test_sample_generator_is_deterministic_and_small(  # type: ignore[no-untyped-def]
    tmp_path,
) -> None:
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"

    first = generate_samples(first_dir)
    second = generate_samples(second_dir)

    assert [path.name for path in first] == [
        "business_sales.csv",
        "sensor_readings.csv",
        "dirty_table.csv",
        "text_corpus.jsonl",
    ]
    assert first[0].read_text(encoding="utf-8-sig") == second[0].read_text(encoding="utf-8-sig")
    assert all(path.stat().st_size < 8_000 for path in first)
