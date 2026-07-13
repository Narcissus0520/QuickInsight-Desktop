from __future__ import annotations

import pytest

from quick_insight.application.errors import UserFacingError
from quick_insight.application.text_corpus import TextImportOptions, TextSplitMode, split_text


def test_split_text_by_non_empty_line_skips_empty_segments() -> None:
    segments, warnings = split_text(
        "第一条\n\n第二条\n",
        TextImportOptions(split_mode=TextSplitMode.NON_EMPTY_LINE),
    )

    assert segments == ("第一条", "第二条")
    assert warnings == ("已跳过 1 个空片段。",)


def test_split_text_by_sentence_handles_chinese_punctuation() -> None:
    segments, warnings = split_text(
        "第一句。第二句！third?",
        TextImportOptions(split_mode=TextSplitMode.SENTENCE),
    )

    assert segments == ("第一句。", "第二句！", "third?")
    assert warnings == ()


def test_custom_delimiter_requires_value() -> None:
    with pytest.raises(UserFacingError) as exc_info:
        split_text("a|b", TextImportOptions(split_mode=TextSplitMode.CUSTOM_DELIMITER))

    assert exc_info.value.code == "TEXT_CORPUS_MISSING_DELIMITER"
