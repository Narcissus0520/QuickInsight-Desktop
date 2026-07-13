from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class ChartRequestDecision:
    url: str
    scheme: str
    allowed: bool
    reason_zh: str


ALLOWED_CHART_SCHEMES = frozenset({"about", "blob", "data", "qrc"})


def classify_chart_request(url: str) -> ChartRequestDecision:
    normalized_url = url.strip()
    scheme = urlsplit(normalized_url).scheme.casefold()
    if scheme in ALLOWED_CHART_SCHEMES:
        return ChartRequestDecision(
            url=normalized_url,
            scheme=scheme,
            allowed=True,
            reason_zh="允许图表本地资源请求。",
        )
    if scheme in {"http", "https", "ws", "wss", "ftp", "ftps"}:
        reason = "图表视图已阻止外部网络请求。"
    elif scheme == "file":
        reason = "图表视图已阻止本地文件请求，避免图表 HTML 读取非授权文件。"
    elif not scheme:
        reason = "图表视图已阻止无协议资源请求。"
    else:
        reason = f"图表视图已阻止不允许的资源协议：{scheme}。"
    return ChartRequestDecision(
        url=normalized_url,
        scheme=scheme,
        allowed=False,
        reason_zh=reason,
    )
