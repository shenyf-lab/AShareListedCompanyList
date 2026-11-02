# src/ashare/sse.py
"""上交所 A 股上市公司列表：主板+科创板分页抓取 commonQuery 接口并解析为统一中文列名。

client 由调用方构造并传入（Referer 需为 http://www.sse.com.cn/），本模块不建 client。
A股总股本/流通股本、B股上市日期、注册地址、公司网址 由后续任务从统计报表补齐。
"""
import datetime

from .clean import empty_if_dash, normalize_date
from .httpclient import HttpClient

SSE_QUERY_URL = "https://query.sse.com.cn/sseQuery/commonQuery.do"

STOCK_TYPE_MAIN = 1  # 主板
STOCK_TYPE_STAR = 8  # 科创板（实测：STOCK_TYPE=8 返回 688xxx，LIST_BOARD=2）

# STATE_CODE -> 上市状态（最小映射，未知码原样透传数字串）
_STATE_CODE_MAP = {"2": "上市", "7": "ST"}


def _query_params(stock_type: int, page: int) -> dict:
    """commonQuery.do 第 page 页请求参数（STOCK_TYPE 区分主板/科创板）。"""
    return {
        "jsonCallBack": "jsonpCallback12345",
        "sqlId": "COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L",
        "type": "inParams",
        "isPagination": "true",
        "STOCK_TYPE": stock_type,
        "REG_PROVINCE": "",
        "CSRC_CODE": "",
        "STOCK_CODE": "",
        "COMPANY_STATUS": "2,4,5,7,8",
        "pageHelp.cacheSize": 1,
        "pageHelp.pageSize": 25,
        "pageHelp.beginPage": page,
        "pageHelp.pageNo": page,
        "pageHelp.endPage": page,
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
        "A股总股本(股)": "",   # 留待统计报表任务补齐
        "A股流通股本(股)": "",
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


def fetch_sse_companies(client: HttpClient) -> list[dict]:
    """抓取上交所主板+科创板 A 股上市公司列表（各自翻页至尾页），返回合并的公司 dict 列表。"""
    fetch_date = datetime.date.today().isoformat()
    companies: list[dict] = []
    for board, stock_type in (("主板", STOCK_TYPE_MAIN), ("科创板", STOCK_TYPE_STAR)):
        rows: list[dict] = []
        page = 1
        page_count = 1  # 占位，第 1 页响应后更新为服务端真实页数
        while page <= page_count:
            resp = client.get_jsonp(SSE_QUERY_URL, params=_query_params(stock_type, page))
            page_help = resp.get("pageHelp") or {}
            page_count = int(page_help.get("pageCount", 1))
            rows.extend(page_help.get("data") or [])
            page += 1
        companies.extend(_parse_company(row, board, fetch_date) for row in rows)
    return companies
