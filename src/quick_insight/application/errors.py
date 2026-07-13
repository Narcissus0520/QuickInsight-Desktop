from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UserFacingError:
    code: str
    title_zh: str
    message_zh: str
    next_action_zh: str
    technical_detail: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "code": self.code,
            "title_zh": self.title_zh,
            "message_zh": self.message_zh,
            "next_action_zh": self.next_action_zh,
            "technical_detail": self.technical_detail,
        }

    def display_text(self) -> str:
        return f"{self.title_zh}：{self.message_zh} 下一步：{self.next_action_zh}"
