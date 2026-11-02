# src/ashare/sse.py
"""上交所 A 股上市公司列表抓取与详情补齐。

列表：主板+科创板分页抓取 commonQuery 接口并解析为统一中文列名。
详情：每家公司请求公司概况/股本结构接口补齐 注册地址/公司网址/股本；
B股上市日期 由一次 STOCK_TYPE=2 列表请求建 {B股代码: 上市日期} 映射后回填。

client 由调用方构造并传入（Referer 需为 http://www.sse.com.cn/），本模块不建 client。
"""
import datetime
from typing import Any

from .clean import empty_if_dash, extract_ascii, normalize_date, normalize_number
from .httpclient import HttpClient

SSE_QUERY_URL = "https://query.sse.com.cn/sseQuery/commonQuery.do"
SSE_PROFILE_URL = "https://query.sse.com.cn/commonQuery.do"  # 公司概况（老路径，实测存活）
SSE_CAPITAL_URL = "https://query.sse.com.cn/security/stock/queryCompanyStockStruct.do"  # 股本结构

STOCK_TYPE_MAIN = 1  # 主板
STOCK_TYPE_STAR = 8  # 科创板（实测：STOCK_TYPE=8 返回 688xxx，LIST_BOARD=2）
STOCK_TYPE_B = 2     # B股（详情补齐：一次列表请求取全部 B 股上市日期）

# STATE_CODE -> 上市状态（最小映射，未知码原样透传数字串）
_STATE_CODE_MAP = {"2": "上市", "7": "ST"}

_JSONP_CALLBACK = "jsonpCallback12345"
_DEGRADE_THRESHOLD = 5  # 连续多少家详情请求失败判定接口不可用


def _query_params(stock_type: int, page: int, page_size: int = 25) -> dict:
    """commonQuery.do 第 page 页请求参数（STOCK_TYPE 区分主板/科创板/B股）。"""
    return {
        "jsonCallBack": _JSONP_CALLBACK,
        "sqlId": "COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L",
        "type": "inParams",
        "isPagination": "true",
        "STOCK_TYPE": stock_type,
        "REG_PROVINCE": "",
        "CSRC_CODE": "",
        "STOCK_CODE": "",
        "COMPANY_STATUS": "2,4,5,7,8",
        "pageHelp.cacheSize": 1,
        "pageHelp.pageSize": page_size,
        "pageHelp.beginPage": page,
        "pageHelp.pageNo": page,
        "pageHelp.endPage": page,
    }


def _profile_params(company_code: str) -> dict:
    """公司概况请求参数（老 sqlId，productid=公司代码）。"""
    return {
        "jsonCallBack": _JSONP_CALLBACK,
        "isPagination": "false",
        "sqlId": "COMMON_SSE_ZQPZ_GP_GPLB_C",
        "productid": company_code,
    }


def _capital_params(company_code: str) -> dict:
    """股本结构请求参数。"""
    return {
        "jsonCallBack": _JSONP_CALLBACK,
        "isPagination": "false",
        "companyCode": company_code,
    }


def _parse_company(row: dict, board: str, fetch_date: str) -> dict:
    """单行原始数据 -> 19 个中文列名的公司 dict（纯函数，供测试直接调用）。"""
    state_code = str(row.get("STATE_CODE") or "").strip()
    return {
        "交易所": "SSE",
        "公司代码": empty_if_dash(row.get("COMPANY_CODE")),
        "A股代码": empty_if_dash(row.get("A_STOCK_CODE")),
        "A股简称": empty_if_dash(row.get("COMPANY_ABBR")),
        "公司全称": empty_if_dash(row.get("FULL_NAME")),
        "英文全称": empty_if_dash(row.get("FULL_NAME_IN_ENGLISH")),
        "板块": board,
        "A股上市日期": normalize_date(row.get("LIST_DATE")),
        "A股总股本(股)": None,  # 详情补齐任务填充（float | None，同 szse 约定）
        "A股流通股本(股)": None,
        "B股代码": empty_if_dash(row.get("B_STOCK_CODE")),
        "B股上市日期": "",
        "省份": empty_if_dash(row.get("AREA_NAME_DESC")),
        "所属行业": empty_if_dash(row.get("CSRC_CODE_DESC")),
        "上市状态": _STATE_CODE_MAP.get(state_code, state_code),
        "退市日期": normalize_date(empty_if_dash(row.get("DELIST_DATE"))),
        "注册地址": "",
        "公司网址": "",
        "抓取日期": fetch_date,
    }


def _fetch_list_rows(client: HttpClient, stock_type: int, page_size: int = 25) -> list[dict]:
    """按 STOCK_TYPE 分页抓取 commonQuery 列表接口的全部行。"""
    rows: list[dict] = []
    page = 1
    page_count = 1  # 占位，第 1 页响应后更新为服务端真实页数
    while page <= page_count:
        resp = client.get_jsonp(SSE_QUERY_URL, params=_query_params(stock_type, page, page_size))
        page_help = resp.get("pageHelp") or {}
        page_count = int(page_help.get("pageCount", 1))
        rows.extend(page_help.get("data") or [])
        page += 1
    return rows


def fetch_sse_companies(client: HttpClient) -> list[dict]:
    """抓取上交所主板+科创板 A 股上市公司列表（各自翻页至尾页），返回合并的公司 dict 列表。"""
    fetch_date = datetime.date.today().isoformat()
    companies: list[dict] = []
    for board, stock_type in (("主板", STOCK_TYPE_MAIN), ("科创板", STOCK_TYPE_STAR)):
        rows = _fetch_list_rows(client, stock_type)
        companies.extend(_parse_company(row, board, fetch_date) for row in rows)
    return companies


def _first_result(resp: Any) -> dict | None:
    """取详情响应 result 的首行；概况接口返回 list、股本接口（isPagination=false）返回 dict。"""
    result = resp.get("result") if isinstance(resp, dict) else None
    if isinstance(result, dict):
        return result
    if isinstance(result, list) and result and isinstance(result[0], dict):
        return result[0]
    return None


def _fetch_b_share_listing_dates(client: HttpClient) -> dict[str, str]:
    """一次 STOCK_TYPE=2 列表请求（一页 50 条）建 {B股代码: 上市日期} 映射。"""
    dates: dict[str, str] = {}
    for row in _fetch_list_rows(client, STOCK_TYPE_B, page_size=50):
        b_code = empty_if_dash(row.get("B_STOCK_CODE"))
        if b_code:
            dates[b_code] = normalize_date(row.get("LIST_DATE"))
    return dates


def _enrich_one(client: HttpClient, row: dict) -> None:
    """单家公司的概况+股本补齐（原地写入）；请求失败抛异常，由调用方计数降级。"""
    code = row.get("公司代码") or ""
    profile = _first_result(client.get_jsonp(SSE_PROFILE_URL, params=_profile_params(code)))
    if profile:
        row["注册地址"] = empty_if_dash(profile.get("COMPANY_ADDRESS"))
        row["公司网址"] = extract_ascii(empty_if_dash(profile.get("WWW_ADDRESS")))
    capital = _first_result(client.get_jsonp(SSE_CAPITAL_URL, params=_capital_params(code)))
    if capital:
        flow = normalize_number(capital.get("AShares"))               # A股流通股本（万股）
        nonflow = normalize_number(capital.get("totalNonFlowShare"))  # 非流通股本（万股）
        if flow is not None:
            row["A股流通股本(股)"] = flow * 1e4
        if flow is not None or nonflow is not None:
            row["A股总股本(股)"] = ((flow or 0.0) + (nonflow or 0.0)) * 1e4


def enrich_sse_details(client: HttpClient, companies: list[dict]) -> list[dict]:
    """原地补齐沪市公司的 注册地址/公司网址/A股总股本(股)/A股流通股本(股)/B股上市日期。

    - 只处理 交易所 == "SSE" 的行；单家失败置空继续（股本 None、其余 ''），已补的不回滚
    - B股上市日期：先回填映射（B股列表失败则留空），与逐家详情互不影响
    - 连续 5 家详情请求失败 → 判定接口不可用，打印提示并停止补齐
    """
    sse_rows = [c for c in companies if c.get("交易所") == "SSE"]
    if not sse_rows:
        return companies
    b_dates: dict[str, str] = {}
    if any(empty_if_dash(c.get("B股代码")) for c in sse_rows):
        try:
            b_dates = _fetch_b_share_listing_dates(client)
        except Exception:
            b_dates = {}
    for row in sse_rows:
        # 确保 5 个详情键存在（最小 dict 直接传入时），不覆盖已有值
        row.setdefault("注册地址", "")
        row.setdefault("公司网址", "")
        row.setdefault("A股总股本(股)", None)
        row.setdefault("A股流通股本(股)", None)
        row.setdefault("B股上市日期", "")
        b_code = empty_if_dash(row.get("B股代码"))
        if b_code and b_code in b_dates:
            row["B股上市日期"] = b_dates[b_code]
    consecutive_failures = 0
    for row in sse_rows:
        try:
            _enrich_one(client, row)
            consecutive_failures = 0
        except Exception:
            consecutive_failures += 1
            if consecutive_failures >= _DEGRADE_THRESHOLD:
                print("详情接口不可用，已降级为列表字段")
                break
    return companies
