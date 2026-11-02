# src/ashare/szse.py
"""深交所 A 股上市公司列表：分页抓取 ShowReport 接口并解析为统一中文列名。

client 由调用方构造并传入（含 Referer 与 x-requested-with 头），本模块不建 client。
"""
import datetime

from .clean import clean_html, empty_if_dash, normalize_date, normalize_number
from .httpclient import HttpClient

SZSE_COMPANY_URL = "https://www.szse.cn/api/report/ShowReport/data"


def _yi_to_shares(value) -> float | None:
    """亿股数值转股数（*1e8）；None/'-' 保持 None。"""
    n = normalize_number(value)
    return n * 1e8 if n is not None else None


def _parse_company(row: dict, fetch_date: str) -> dict:
    """单行原始数据 -> 19 个中文列名的公司 dict（纯函数，供测试直接调用）。"""
    code = str(row.get("agdm") or "").strip().zfill(6)  # 防御：代码缺失补零
    return {
        "交易所": "SZSE",
        "公司代码": code,
        "A股代码": code,
        "A股简称": clean_html(empty_if_dash(row.get("agjc"))),
        "公司全称": "",
        "英文全称": "",
        "板块": empty_if_dash(row.get("bk")),
        "A股上市日期": normalize_date(row.get("agssrq")),
        "A股总股本(股)": _yi_to_shares(row.get("agzgb")),
        "A股流通股本(股)": _yi_to_shares(row.get("agltgb")),
        "B股代码": "",
        "B股上市日期": "",
        "省份": "",
        "所属行业": empty_if_dash(row.get("sshymc")),
        "上市状态": "上市",
        "退市日期": "",
        "注册地址": "",
        "公司网址": "",
        "抓取日期": fetch_date,
    }


def fetch_szse_companies(client: HttpClient) -> list[dict]:
    """抓取深交所 A 股上市公司列表（翻页至尾页），返回公司 dict 列表。"""
    fetch_date = datetime.date.today().isoformat()
    rows: list[dict] = []
    pageno = 1
    pagecount = 1  # 占位，第 1 页响应后更新为服务端真实页数
    while pageno <= pagecount:
        resp = client.get_json(
            SZSE_COMPANY_URL,
            params={"SHOWTYPE": "JSON", "CATALOGID": "1110", "PAGENO": pageno},
        )
        meta = resp[0]["metadata"]
        pagecount = int(meta.get("pagecount", 1))
        rows.extend(resp[0]["data"])
        pageno += 1
    return [_parse_company(row, fetch_date) for row in rows]
