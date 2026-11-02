# tests/test_szse.py
import json
from pathlib import Path

import pytest

from src.ashare.storage import STATS_COLUMNS
from src.ashare.szse import fetch_szse_companies, fetch_szse_market_stats, _parse_company

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


# ---------- 快照护栏：空/残数据必须抛错，阻止覆盖上次完好快照 ----------

def test_fetch_empty_list_raises():
    class EmptyDataClient:
        def get_json(self, url, params=None):
            return [{"metadata": {"pagecount": 1, "recordcount": 2905}, "data": []}]
    with pytest.raises(RuntimeError, match="0 行"):
        fetch_szse_companies(EmptyDataClient())

def test_fetch_rows_far_below_recordcount_raises():
    class PagecountRenamedClient:
        """pagecount 键改名场景：只剩第 1 页 3 行，服务端仍自报 recordcount=2905。"""
        def get_json(self, url, params=None):
            resp = json.loads(FIX.read_text(encoding="utf-8"))
            resp[0]["metadata"].pop("pagecount")
            return resp
    with pytest.raises(RuntimeError, match="2905"):
        fetch_szse_companies(PagecountRenamedClient())

def test_fetch_rows_below_floor_without_recordcount_raises():
    class NoTotalsClient:
        """recordcount 也丢失时，走 500 行绝对下限护栏。"""
        def get_json(self, url, params=None):
            resp = json.loads(FIX.read_text(encoding="utf-8"))
            resp[0]["metadata"].pop("pagecount")
            resp[0]["metadata"].pop("recordcount")
            return resp
    with pytest.raises(RuntimeError, match="500"):
        fetch_szse_companies(NoTotalsClient())


# ---------- Task 7: 市场统计 ----------

STATS_FIX = Path(__file__).parent / "fixtures" / "szse_stats.json"

def test_fetch_szse_market_stats_maps_indicators_only():
    resp = json.loads(STATS_FIX.read_text(encoding="utf-8"))
    class StatsClient:
        def __init__(self): self.params = None
        def get_json(self, url, params=None):
            self.params = params
            return resp
    client = StatsClient()
    rows = fetch_szse_market_stats(client, "2026-10-30")
    assert client.params == {"SHOWTYPE": "JSON", "CATALOGID": "1803_after", "txtQueryDate": "2026-10-30"}
    assert len(rows) == 1
    r = rows[0]
    assert set(r) == set(STATS_COLUMNS)
    assert r["日期"] == "2026-10-30" and r["交易所"] == "SZSE" and r["板块"] == "整体"
    assert r["上市公司数"] == 2908 and r["上市证券数"] == 24088
    assert r["总股本(亿股)"] == 27816.47 and r["流通股本(亿股)"] == 24697.01
    assert r["总市值(亿元)"] == 363558.55           # 千分位已清洗
    assert r["流通市值(亿元)"] == 309237.01
    assert r["平均市盈率"] == 24.75
    assert r["成交金额(亿元)"] == 9109.10 and r["平均股价(元)"] == 13.06 and r["换手率(%)"] == 2.47
    assert "深证成指" not in str(r)                    # 指数行被排除

def test_fetch_szse_market_stats_empty_returns_no_rows():
    class EmptyClient:
        def get_json(self, url, params=None): return [{"metadata": {}, "data": []}]
    assert fetch_szse_market_stats(EmptyClient(), "2026-10-31") == []

def test_fetch_szse_market_stats_missing_company_count_returns_no_rows():
    class IndexOnlyClient:
        def get_json(self, url, params=None):
            return [{"metadata": {}, "data": [{"zbmc": "深证成指", "brsz": "10,833.78"}]}]
    assert fetch_szse_market_stats(IndexOnlyClient(), "2026-10-31") == []
