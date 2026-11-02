# tests/test_szse.py
import json
from pathlib import Path
from src.ashare.szse import fetch_szse_companies, _parse_company

FIX = Path(__file__).parent / "fixtures" / "szse_companies_p1.json"

class FakeClient:
    def __init__(self, pages): self.pages = list(pages)
    def get_json(self, url, params=None):
        p = params["PAGENO"]
        return self.pages[p - 1] if p <= len(self.pages) else empty_page()

def empty_page():
    return [{"metadata": {"pagecount": 2, "recordcount": 3}, "data": []}]

def test_parse_company_strips_html_and_maps_fields():
    row = json.loads(FIX.read_text(encoding="utf-8"))[0]["data"][0]
    d = _parse_company(row, fetch_date="2026-11-02")
    assert d["交易所"] == "SZSE"
    assert d["公司代码"] == "000001" and d["A股代码"] == "000001"
    assert d["A股简称"] == "平安银行"          # HTML 已剥离
    assert d["板块"] == "主板"
    assert d["A股上市日期"] == "1991-04-03"
    assert d["A股总股本(股)"] == 194.05e8       # 亿股 → 股
    assert d["A股流通股本(股)"] == 194.05e8
    assert d["所属行业"] == "J 金融业"
    assert d["上市状态"] == "上市"
    assert d["公司全称"] == "" and d["注册地址"] == ""   # 深市无此数据
    assert d["抓取日期"] == "2026-11-02"

def test_fetch_pages_until_recordcount():
    p1 = json.loads(FIX.read_text(encoding="utf-8"))
    p1[0]["metadata"]["pagecount"] = 2
    p1[0]["metadata"]["recordcount"] = 3
    p1[0]["data"] = p1[0]["data"][:3]
    rows = fetch_szse_companies(FakeClient([p1]))
    assert len(rows) == 3
    assert {r["公司代码"] for r in rows} == {"000001", "000002", "000010"}
