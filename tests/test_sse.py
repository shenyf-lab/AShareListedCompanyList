# tests/test_sse.py
import json
from pathlib import Path
from src.ashare.sse import fetch_sse_companies, _parse_company, STOCK_TYPE_MAIN, STOCK_TYPE_STAR

FIX = Path(__file__).parent / "fixtures" / "sse_companies_p1.json"

def sample(n=3):
    d = json.loads(FIX.read_text(encoding="utf-8"))
    d["pageHelp"]["data"] = d["pageHelp"]["data"][:n]
    return d

class FakeClient:
    def __init__(self): self.calls = []
    def get_jsonp(self, url, params=None):
        self.calls.append(params)
        r = sample()
        r["pageHelp"]["pageCount"] = 1
        return r

def test_parse_company_maps_fields():
    row = json.loads(FIX.read_text(encoding="utf-8"))["pageHelp"]["data"][0]  # 600032
    d = _parse_company(row, board="主板", fetch_date="2026-11-02")
    assert d["交易所"] == "SSE"
    assert d["公司代码"] == "600032" and d["A股代码"] == "600032"
    assert d["A股简称"] == "浙江新能" and d["公司全称"] == "浙江省新能源投资集团股份有限公司"
    assert d["英文全称"] == "Zhejiang Provincial New Energy Investment Group Co., Ltd."
    assert d["A股上市日期"] == "2021-05-25"
    assert d["省份"] == "浙江省"
    assert d["所属行业"] == "电力、热力、燃气及水生产和供应业"
    assert d["板块"] == "主板" and d["抓取日期"] == "2026-11-02"

def test_parse_company_b_share_and_delist_date():
    rows = json.loads(FIX.read_text(encoding="utf-8"))["pageHelp"]["data"]
    huangshan = next(r for r in rows if r["COMPANY_CODE"] == "600054")
    d = _parse_company(huangshan, board="主板", fetch_date="2026-11-02")
    assert d["B股代码"] == "900942" and d["退市日期"] == ""

def test_parse_company_state_code_mapping():
    rows = json.loads(FIX.read_text(encoding="utf-8"))["pageHelp"]["data"]
    by_code = {r["COMPANY_CODE"]: r for r in rows}
    assert _parse_company(by_code["600032"], "主板", "2026-11-02")["上市状态"] == "上市"
    assert _parse_company(by_code["600053"], "主板", "2026-11-02")["上市状态"] == "ST"
    unknown = {**by_code["600032"], "STATE_CODE": "9"}
    assert _parse_company(unknown, "主板", "2026-11-02")["上市状态"] == "9"  # 未知码原样透传

def test_fetch_covers_both_stock_types():
    c = FakeClient()
    rows = fetch_sse_companies(c)
    types = {p["STOCK_TYPE"] for p in c.calls}
    assert types == {STOCK_TYPE_MAIN, STOCK_TYPE_STAR}
    assert len(rows) == 6                      # 3 主板 + 3 科创板（同一 fixture 复用）
    assert all(r["交易所"] == "SSE" for r in rows)
