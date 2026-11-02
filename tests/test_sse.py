# tests/test_sse.py
import json
from pathlib import Path

import pytest

from src.ashare.sse import (
    fetch_sse_companies,
    _parse_company,
    enrich_sse_details,
    STOCK_TYPE_MAIN,
    STOCK_TYPE_STAR,
)

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


# ---------- Task 5: 详情补齐 ----------

PROFILE_FIX = Path(__file__).parent / "fixtures" / "sse_detail_profile.json"
CAPITAL_FIX = Path(__file__).parent / "fixtures" / "sse_detail_capital.json"
BSHARE_FIX = Path(__file__).parent / "fixtures" / "sse_bshare_p1.json"

# 实测接口路径（概况在老路径，B股列表与 Task 4 列表同路径）
PROFILE_URL = "https://query.sse.com.cn/commonQuery.do"
CAPITAL_URL = "https://query.sse.com.cn/security/stock/queryCompanyStockStruct.do"
LIST_URL = "https://query.sse.com.cn/sseQuery/commonQuery.do"


def load_fixture(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def base_companies():
    """待补齐的沪市公司行（Task 4 产出形态：详情字段已初始化为空）。"""
    return [{"交易所": "SSE", "公司代码": "600000", "A股代码": "600000", "B股代码": "",
             "注册地址": "", "公司网址": "", "A股总股本(股)": None, "A股流通股本(股)": None, "B股上市日期": ""}]


def test_parse_company_initializes_detail_fields_empty():
    row = json.loads(FIX.read_text(encoding="utf-8"))["pageHelp"]["data"][0]
    d = _parse_company(row, board="主板", fetch_date="2026-11-02")
    assert d["A股总股本(股)"] is None and d["A股流通股本(股)"] is None  # float | None 约定（同 szse）
    assert d["B股上市日期"] == "" and d["注册地址"] == "" and d["公司网址"] == ""


def test_enrich_fills_address_website_capital():
    profile = load_fixture(PROFILE_FIX)
    capital = load_fixture(CAPITAL_FIX)

    class DetailClient:
        def get_jsonp(self, url, params=None):
            if url == PROFILE_URL:
                assert params["sqlId"] == "COMMON_SSE_ZQPZ_GP_GPLB_C"
                assert params["productid"] == "600000"
                return profile
            if url == CAPITAL_URL:
                assert params["companyCode"] == "600000"
                return capital
            raise AssertionError(f"意外的请求: {url} {params}")

    rows = enrich_sse_details(DetailClient(), base_companies())
    assert rows[0]["注册地址"] == profile["result"][0]["COMPANY_ADDRESS"]
    assert rows[0]["公司网址"] == "http://www.spdb.com.cn"  # extract_ascii 去掉尾部中文噪声
    assert isinstance(rows[0]["A股总股本(股)"], float)
    assert rows[0]["A股总股本(股)"] == pytest.approx(29352168000.0)  # (非流通0 + 流通2935216.80万) × 1e4
    assert rows[0]["A股流通股本(股)"] == pytest.approx(29352168000.0)
    assert rows[0]["A股总股本(股)"] >= rows[0]["A股流通股本(股)"] > 0


def test_enrich_single_failure_leaves_blank():
    class DeadClient:
        def __init__(self): self.n = 0
        def get_jsonp(self, url, params=None):
            self.n += 1; raise RuntimeError("down")

    rows = [{"交易所": "SSE", "公司代码": "600001", "B股代码": ""}]
    result = enrich_sse_details(DeadClient(), rows)  # 单家失败 → 置空继续，不抛
    assert result is rows
    assert rows[0]["注册地址"] == "" and rows[0]["公司网址"] == ""
    assert rows[0]["A股总股本(股)"] is None and rows[0]["A股流通股本(股)"] is None
    assert rows[0]["B股上市日期"] == ""


def test_enrich_consecutive_failures_degrades_and_stops(capsys):
    profile = load_fixture(PROFILE_FIX)
    capital = load_fixture(CAPITAL_FIX)

    class HalfDeadClient:
        """600000/600001 正常，其余公司的请求全挂。"""
        def __init__(self):
            self.ok = {"600000", "600001"}
            self.requested = []

        def get_jsonp(self, url, params=None):
            code = (params or {}).get("productid") or (params or {}).get("companyCode")
            self.requested.append(code)
            if code in self.ok:
                return profile if url == PROFILE_URL else capital
            raise RuntimeError("down")

    codes = ["600000", "600001", "600002", "600003", "600004", "600005", "600006", "600007"]
    rows = [{**base_companies()[0], "公司代码": c, "A股代码": c} for c in codes]
    client = HalfDeadClient()
    enrich_sse_details(client, rows)
    assert rows[0]["注册地址"] == "上海市中山东一路12号"  # 已补的不回滚
    assert rows[1]["注册地址"] == "上海市中山东一路12号"
    assert rows[0]["A股流通股本(股)"] == pytest.approx(29352168000.0)
    for r in rows[2:]:
        assert r["注册地址"] == "" and r["公司网址"] == ""
        assert r["A股总股本(股)"] is None and r["A股流通股本(股)"] is None
    assert client.requested.count("600006") == 1  # 第 5 家连续失败（概况失败后股本不再请求）
    assert "600007" not in client.requested       # 降级后停止：后续公司不再请求
    assert "已降级为列表字段" in capsys.readouterr().out


def test_enrich_failure_counter_resets_on_success():
    profile = load_fixture(PROFILE_FIX)
    capital = load_fixture(CAPITAL_FIX)

    class AlternatingClient:
        """偶数代码正常、奇数代码失败。"""
        def __init__(self):
            self.requested = []

        def get_jsonp(self, url, params=None):
            code = (params or {}).get("productid") or (params or {}).get("companyCode")
            self.requested.append(code)
            if int(code) % 2 == 0:
                return profile if url == PROFILE_URL else capital
            raise RuntimeError("down")

    codes = [f"60000{i}" for i in range(8)]
    rows = [{**base_companies()[0], "公司代码": c, "A股代码": c} for c in codes]
    client = AlternatingClient()
    enrich_sse_details(client, rows)
    assert all(c in client.requested for c in codes)  # 永不连续 5 家 → 全部处理
    for c, r in zip(codes, rows):
        if int(c) % 2 == 0:
            assert r["注册地址"] == "上海市中山东一路12号"
        else:
            assert r["注册地址"] == "" and r["A股总股本(股)"] is None


def test_enrich_b_share_dates_from_single_list_request():
    bshare = load_fixture(BSHARE_FIX)
    profile = load_fixture(PROFILE_FIX)
    capital = load_fixture(CAPITAL_FIX)

    class BListClient:
        def __init__(self):
            self.list_params = []

        def get_jsonp(self, url, params=None):
            if url == LIST_URL:
                self.list_params.append(params)
                return bshare
            if url == PROFILE_URL:
                return profile
            if url == CAPITAL_URL:
                return capital
            raise AssertionError(f"意外的请求: {url} {params}")

    client = BListClient()

    def row(code, b_code):
        return {**base_companies()[0], "公司代码": code, "A股代码": code, "B股代码": b_code}

    szse_row = {"交易所": "SZSE", "公司代码": "000001"}
    rows = [row("600054", "900942"), row("600094", "900940"),
            row("600000", ""), row("600610", "900999"), szse_row]
    enrich_sse_details(client, rows)
    assert rows[0]["B股上市日期"] == "1996-11-22"  # 黄山旅游（B股列表回填，normalize_date）
    assert rows[1]["B股上市日期"] == "1996-07-26"  # 大名城
    assert rows[2]["B股上市日期"] == ""            # 无 B 股
    assert rows[3]["B股上市日期"] == ""            # 未匹配的 B 股代码保持为空
    assert rows[4] == {"交易所": "SZSE", "公司代码": "000001"}  # 非沪市行原样不动
    assert len(client.list_params) == 1           # B 股列表只请求一次
    p = client.list_params[0]
    assert p["STOCK_TYPE"] == 2 and p["sqlId"] == "COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L"
    assert p["pageHelp.pageSize"] == 50
    assert rows[0]["注册地址"] == "上海市中山东一路12号"  # 其余详情照常补齐


def test_enrich_b_list_failure_leaves_dates_empty():
    profile = load_fixture(PROFILE_FIX)
    capital = load_fixture(CAPITAL_FIX)

    class BListDeadClient:
        def get_jsonp(self, url, params=None):
            if url == LIST_URL:
                raise RuntimeError("down")
            if url == PROFILE_URL:
                return profile
            if url == CAPITAL_URL:
                return capital
            raise AssertionError(f"意外的请求: {url} {params}")

    rows = [{**base_companies()[0], "公司代码": "600054", "A股代码": "600054", "B股代码": "900942"}]
    enrich_sse_details(BListDeadClient(), rows)
    assert rows[0]["B股上市日期"] == ""                     # B 股列表失败 → 日期留空
    assert rows[0]["注册地址"] == "上海市中山东一路12号"     # 其余详情不受影响
    assert rows[0]["A股流通股本(股)"] == pytest.approx(29352168000.0)
