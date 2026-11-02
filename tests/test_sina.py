# tests/test_sina.py
import datetime
import json
from pathlib import Path

import pytest

from src.ashare.sina import (
    SINA_FINANCE_URL,
    STATEMENT_SOURCES,
    _parse_statement,
    fetch_sina_statement,
    paper_code_for,
)

FIX = Path(__file__).parent / "fixtures" / "sina_lrb_sample.json"

TODAY_YEAR = datetime.date.today().year
# years 取值使报告期年份下限（当前年-years+1）恰为 2025/2026，断言不随真实日期漂移
YEARS_FROM_2025 = TODAY_YEAR - 2025 + 1  # 下限 2025：fixture 全部报告期年份都保留
YEARS_FROM_2026 = TODAY_YEAR - 2026 + 1  # 下限 2026：2025 两期被 years 过滤


def load_data():
    """fixture（完整响应）-> 接口 result.data，即 _parse_statement 的入参形态。"""
    return json.loads(FIX.read_text(encoding="utf-8"))["result"]["data"]


class FakeClient:
    def __init__(self, resp):
        self.resp = resp
        self.calls = []

    def get_json(self, url, params=None):
        self.calls.append((url, params))
        return self.resp


# ---------- paper_code 映射 ----------

def test_paper_code_for_sse_and_szse():
    assert paper_code_for("SSE", "600000") == "sh600000"
    assert paper_code_for("SZSE", "000002") == "sz000002"

def test_paper_code_for_unknown_exchange_raises():
    with pytest.raises(ValueError, match="BJSE"):
        paper_code_for("BJSE", "830799")


# ---------- _parse_statement：报告期筛选 ----------

def test_parse_keeps_only_annual_and_semiannual():
    rows = _parse_statement(load_data(), "000002", YEARS_FROM_2025)
    assert [r["报告期"] for r in rows] == ["2026-06-30", "2025-12-31", "2025-06-30"]  # 季报 20260930 丢弃
    assert [r["报告类型"] for r in rows] == ["半年报", "年报", "半年报"]

def test_parse_years_filter_boundary():
    rows = _parse_statement(load_data(), "000002", YEARS_FROM_2026)
    assert [r["报告期"] for r in rows] == ["2026-06-30"]  # 2025 两期被 years 过滤；20260930 仍被类型过滤


# ---------- _parse_statement：元信息与科目 ----------

def test_parse_metadata_fields():
    rows = {r["报告期"]: r for r in _parse_statement(load_data(), "000002", YEARS_FROM_2025)}
    annual = rows["2025-12-31"]
    assert annual["代码"] == "000002"
    assert annual["披露日"] == "2026-04-01" and annual["是否审计"] == "是" and annual["币种"] == "CNY"
    semi = rows["2026-06-30"]
    assert semi["披露日"] == "2026-08-28" and semi["是否审计"] == "未审计" and semi["币种"] == "CNY"

def test_parse_fixed_columns_come_first():
    row = _parse_statement(load_data(), "000002", YEARS_FROM_2025)[0]
    assert list(row)[:6] == ["代码", "报告期", "报告类型", "披露日", "是否审计", "币种"]

def test_parse_item_values_as_float():
    rows = {r["报告期"]: r for r in _parse_statement(load_data(), "000002", YEARS_FROM_2025)}
    revenue = rows["2026-06-30"]["营业收入"]
    assert isinstance(revenue, float) and revenue == pytest.approx(70169108549.07)  # ".070000" 尾缀已化净
    assert rows["2025-12-31"]["营业总收入"] == pytest.approx(233432768960.43)

def test_parse_none_value_item():
    rows = {r["报告期"]: r for r in _parse_statement(load_data(), "000002", YEARS_FROM_2025)}
    # 万科利润表首条"利息收入"为 null，第二条同名科目 350673182.08 → 保留首个即 None
    assert rows["2026-06-30"]["利息收入"] is None

def test_parse_dash_value_becomes_none():
    data = {
        "report_date": [{"date_value": "20251231"}],
        "report_list": {"20251231": {
            "publish_date": "20260401", "is_audit": "是", "rCurrency": "CNY",
            "data": [
                {"item_title": "营业收入", "item_value": "-"},
                {"item_title": "净利润", "item_value": "100.5"},
            ],
        }},
    }
    rows = _parse_statement(data, "000002", YEARS_FROM_2025)
    assert rows[0]["营业收入"] is None and rows[0]["净利润"] == 100.5

def test_parse_duplicate_title_keeps_first():
    data = {
        "report_date": [{"date_value": "20251231"}],
        "report_list": {"20251231": {
            "publish_date": "20260401", "is_audit": "是", "rCurrency": "CNY",
            "data": [
                {"item_title": "利息收入", "item_value": "111.0"},
                {"item_title": "利息收入", "item_value": "222.0"},
            ],
        }},
    }
    rows = _parse_statement(data, "000002", YEARS_FROM_2025)
    assert rows[0]["利息收入"] == 111.0

def test_parse_empty_data_returns_empty_list():
    assert _parse_statement({}, "000002", 10) == []
    assert _parse_statement({"report_date": [], "report_list": {}}, "000002", 10) == []


# ---------- fetch_sina_statement ----------

def test_fetch_sends_params_and_strips_prefix():
    client = FakeClient(json.loads(FIX.read_text(encoding="utf-8")))
    rows = fetch_sina_statement(client, "sz000002", "income", years=YEARS_FROM_2025)
    assert len(client.calls) == 1  # 单页 num=1000 即全量报告期，无需分页拼接
    url, params = client.calls[0]
    assert url == SINA_FINANCE_URL
    assert params == {"paperCode": "sz000002", "source": "lrb",
                      "type": "0", "page": "1", "num": "1000"}
    assert {r["代码"] for r in rows} == {"000002"}  # paper_code 去市场前缀后落行
    assert [r["报告期"] for r in rows] == ["2026-06-30", "2025-12-31", "2025-06-30"]

def test_fetch_statement_sources_mapping():
    for statement, source in STATEMENT_SOURCES.items():
        client = FakeClient({"result": {"data": {}}})
        fetch_sina_statement(client, "sh600000", statement)
        assert client.calls[0][1]["source"] == source

def test_fetch_unknown_statement_raises():
    with pytest.raises(ValueError, match="profit"):
        fetch_sina_statement(FakeClient({}), "sz000002", "profit")
