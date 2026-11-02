# src/ashare/sina.py
"""新浪财报抓取与解析：沪深 A 股公司的年报/半年报三大报表（利润/资产负债/现金流量）。

接口 CompanyFinanceService.getFinanceReport2022 单页（num=1000）即返回全部报告期，
每期自带 publish_date/is_audit/rCurrency 元信息与全科目明细（item_title/item_value）。
本模块只保留年报（1231）/半年报（0630）报告期（季报丢弃），按 years 截取近年；
行内科目为动态键（item_value 转 float，'-'/null -> None，重复科目保留首个）。
client 由调用方构造并传入（Referer 需为 https://finance.sina.com.cn/），本模块不建 client。
"""
import datetime

from .clean import normalize_date, normalize_number
from .httpclient import HttpClient

SINA_FINANCE_URL = "https://quotes.sina.cn/cn/api/openapi.php/CompanyFinanceService.getFinanceReport2022"

# 报表名 -> 接口 source 参数（lrb 利润表 / fzb 资产负债表 / llb 现金流量表）
STATEMENT_SOURCES = {"income": "lrb", "balance": "fzb", "cashflow": "llb"}

# 交易所 -> paperCode 市场前缀（新浪 paperCode = 小写前缀 + 6 位证券代码）
_EXCHANGE_PREFIXES = {"SSE": "sh", "SZSE": "sz"}

# 报告期 YYYYMMDD 后 4 位 -> 报告类型；0331/0930 季报不在表中即被丢弃
_REPORT_TYPES = {"1231": "年报", "0630": "半年报"}


def paper_code_for(exchange: str, code: str) -> str:
    """交易所+证券代码 -> 新浪 paperCode：'SSE'+'600000' -> 'sh600000'；未知交易所抛 ValueError。"""
    prefix = _EXCHANGE_PREFIXES.get(exchange)
    if prefix is None:
        raise ValueError(f"不支持的交易所 {exchange}（仅支持 {'/'.join(_EXCHANGE_PREFIXES)}）")
    return f"{prefix}{code}"


def _parse_statement(data: dict, code: str, years: int) -> list[dict]:
    """接口 result.data -> 行 dict 列表（纯函数，供测试直接调用）。

    每行 = {代码, 报告期(YYYY-MM-DD), 报告类型(年报|半年报), 披露日, 是否审计, 币种, **科目…}：
    - 报告期过滤：仅保留 1231/0630 后缀（季报丢弃）；years 过滤：报告期年份 >= 当前年-years+1
    - 科目为动态键：item_value 转 float，'-'/null -> None；重复 item_title 保留首个
    """
    cutoff_year = datetime.date.today().year - years + 1
    rows: list[dict] = []
    for period in data.get("report_date") or []:
        date_value = str((period or {}).get("date_value") or "")
        if len(date_value) != 8 or not date_value.isdigit():
            continue
        report_type = _REPORT_TYPES.get(date_value[4:])
        if report_type is None:
            continue
        if int(date_value[:4]) < cutoff_year:
            continue
        report = (data.get("report_list") or {}).get(date_value)
        if not report:  # report_list 缺该期（接口残缺）→ 跳过
            continue
        row = {
            "代码": code,
            "报告期": normalize_date(date_value),
            "报告类型": report_type,
            "披露日": normalize_date(report.get("publish_date")),
            "是否审计": report.get("is_audit") or "",
            "币种": report.get("rCurrency") or "",
        }
        for item in report.get("data") or []:
            title = item.get("item_title")
            if title and title not in row:  # 重复科目（及与固定列同名）保留首个
                row[title] = normalize_number(item.get("item_value"))
        rows.append(row)
    return rows


def fetch_sina_statement(client: HttpClient, paper_code: str, statement: str,
                         years: int = 10) -> list[dict]:
    """抓取单家公司单张报表（一次请求取全部报告期），返回解析后的行 dict 列表。

    paper_code 形如 sh600000（paper_code_for 产出），行内 代码 为去市场前缀的证券代码。
    """
    if statement not in STATEMENT_SOURCES:
        raise ValueError(f"未知报表 {statement}（可选 {'/'.join(sorted(STATEMENT_SOURCES))}）")
    resp = client.get_json(SINA_FINANCE_URL, params={
        "paperCode": paper_code,
        "source": STATEMENT_SOURCES[statement],
        "type": "0",
        "page": "1",
        "num": "1000",
    })
    data = ((resp or {}).get("result") or {}).get("data") or {}
    return _parse_statement(data, paper_code[2:], years)
