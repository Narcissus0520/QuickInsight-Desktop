from __future__ import annotations

from quick_insight.application.errors import UserFacingError


def test_user_facing_error_contains_chinese_guidance_and_detail() -> None:
    error = UserFacingError(
        code="TEST",
        title_zh="无法导入",
        message_zh="文件格式暂不支持。",
        next_action_zh="请选择 CSV 或 Excel 文件。",
        technical_detail="parser=none",
    )

    assert error.to_dict()["technical_detail"] == "parser=none"
    assert "下一步" in error.display_text()
    assert "请选择" in error.display_text()
