from __future__ import annotations

from quick_insight.charts import ALLOWED_CHART_SCHEMES, classify_chart_request


def test_chart_request_policy_allows_only_local_chart_schemes() -> None:
    assert frozenset({"about", "blob", "data", "qrc"}) == ALLOWED_CHART_SCHEMES
    assert classify_chart_request("qrc:/quick-insight/charts/").allowed is True
    assert classify_chart_request("data:image/png;base64,AA==").allowed is True
    assert classify_chart_request("blob:null/123").allowed is True
    assert classify_chart_request("about:blank").allowed is True


def test_chart_request_policy_blocks_external_file_and_unknown_schemes() -> None:
    https_decision = classify_chart_request("https://example.com/plotly.js")
    file_decision = classify_chart_request("file:///C:/Users/example/secret.csv")
    unknown_decision = classify_chart_request("javascript:alert(1)")

    assert https_decision.allowed is False
    assert https_decision.scheme == "https"
    assert "外部网络请求" in https_decision.reason_zh
    assert file_decision.allowed is False
    assert file_decision.scheme == "file"
    assert "本地文件请求" in file_decision.reason_zh
    assert unknown_decision.allowed is False
    assert unknown_decision.scheme == "javascript"
