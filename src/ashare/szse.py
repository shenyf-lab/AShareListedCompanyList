# src/ashare/szse.py
"""深交所 A 股上市公司列表与市场统计：抓取 ShowReport 接口并解析为统一中文列名。

列表：分页抓取上市公司列表；统计：市场统计（1803_after）指标行映射为长表一行。
client 由调用方构造并传入（含 Referer 与 x-requested-with 头），本模块不建 client。
"""
import datetime

from .clean import clean_html, empty_if_dash, guard_row_count, normalize_date, normalize_number
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
    """抓取深交所 A 股上市公司列表（翻页至尾页），返回公司 dict 列表。

    护栏：抓完校验服务端自报总数（metadata.recordcount），空列表或行数 < 95%
    （自报总数缺失时 < 500 行）抛 RuntimeError，阻止残缺快照覆盖上次完快照。
    """
    fetch_date = datetime.date.today().isoformat()
    rows: list[dict] = []
    pageno = 1
    pagecount = 1  # 占位，第 1 页响应后更新为服务端真实页数
    recordcount = 0  # 服务端自报总数（第 1 页响应读取；缺失/非法按 0 处理）
    while pageno <= pagecount:
        resp = client.get_json(
            SZSE_COMPANY_URL,
            params={"SHOWTYPE": "JSON", "CATALOGID": "1110", "PAGENO": pageno},
        )
        meta = resp[0]["metadata"]
        pagecount = int(meta.get("pagecount", 1))
        if pageno == 1:
            try:
                recordcount = int(meta.get("recordcount") or 0)
            except (TypeError, ValueError):
                recordcount = 0
        rows.extend(resp[0]["data"])
        pageno += 1
    guard_row_count(len(rows), recordcount, "深交所公司列表")
    return [_parse_company(row, fetch_date) for row in rows]


SZSE_STATS_CATALOG_ID = "1803_after"  # 市场统计（深圳市场 tab）

# 统计指标名（zbmc 精确匹配）-> STATS_COLUMNS 列名；指数行（深证成指等）不在表中即被排除
_SZSE_STATS_INDICATORS = {
    "上市公司数": "上市公司数",
    "上市证券数": "上市证券数",
    "股票总股本（亿）": "总股本(亿股)",
    "股票流通股本（亿）": "流通股本(亿股)",
    "股票总市值（亿元）": "总市值(亿元)",
    "股票流通市值（亿元）": "流通市值(亿元)",
    "股票成交金额（亿元）": "成交金额(亿元)",
    "平均股票价格（元）": "平均股价(元)",
    "股票平均市盈率": "平均市盈率",
    "股票平均换手率": "换手率(%)",
}


def fetch_szse_market_stats(client: HttpClient, date: str) -> list[dict]:
    """抓取深交所市场统计（深圳市场 tab）→ 长表 0 或 1 行（SZSE/整体）。

    指标行按 zbmc 精确匹配映射，值取 brsz（本日数值）过 normalize_number 清洗千分位；
    data 为空或缺"上市公司数"指标行 → 返回 []。
    """
    resp = client.get_json(
        SZSE_COMPANY_URL,
        params={"SHOWTYPE": "JSON", "CATALOGID": SZSE_STATS_CATALOG_ID, "txtQueryDate": date},
    )
    values: dict[str, float | None] = {}
    for item in resp[0].get("data") or []:
        column = _SZSE_STATS_INDICATORS.get(str(item.get("zbmc") or "").strip())
        if column:
            values[column] = normalize_number(item.get("brsz"))
    if values.get("上市公司数") is None:
        return []
    return [{
        "日期": date,
        "交易所": "SZSE",
        "板块": "整体",
        "上市公司数": values.get("上市公司数"),
        "上市证券数": values.get("上市证券数"),
        "总股本(亿股)": values.get("总股本(亿股)"),
        "流通股本(亿股)": values.get("流通股本(亿股)"),
        "总市值(亿元)": values.get("总市值(亿元)"),
        "流通市值(亿元)": values.get("流通市值(亿元)"),
        "平均市盈率": values.get("平均市盈率"),
        "成交金额(亿元)": values.get("成交金额(亿元)"),
        "平均股价(元)": values.get("平均股价(元)"),
        "换手率(%)": values.get("换手率(%)"),
    }]
