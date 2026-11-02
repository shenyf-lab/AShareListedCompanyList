# src/ashare/storage.py
"""存储层：公司快照落盘（CSV + 三 sheet xlsx）与市场统计幂等追加。

输入均为上游解析好的 list[dict]（中文列名齐全），本模块不抓取、不清洗，
只负责列序、排序、幂等去重与落盘；CSV 一律 utf-8-sig（带 BOM，Excel 直开不乱码）。
"""
import datetime
from pathlib import Path

import pandas as pd

COMPANY_COLUMNS: list[str] = [
    "交易所", "公司代码", "A股代码", "A股简称", "公司全称", "英文全称", "板块",
    "A股上市日期", "A股总股本(股)", "A股流通股本(股)", "B股代码", "B股上市日期",
    "省份", "所属行业", "上市状态", "退市日期", "注册地址", "公司网址", "抓取日期",
]

STATS_COLUMNS: list[str] = [
    "日期", "交易所", "板块", "上市公司数", "上市证券数", "总股本(亿股)",
    "流通股本(亿股)", "总市值(亿元)", "流通市值(亿元)", "平均市盈率",
    "成交金额(亿元)", "平均股价(元)", "换手率(%)",
]

COMPANIES_CSV = "companies_latest.csv"
MARKET_STATS_CSV = "market_stats.csv"
STATS_KEYS = ["日期", "交易所", "板块"]  # 幂等键


def _int_if_whole_float(value):
    """值为整数的 float 转 int（29352168000.0 → 29352168000），其余类型/值原样返回。"""
    return int(value) if isinstance(value, float) and value.is_integer() else value


def _strip_float_tail(df: pd.DataFrame) -> pd.DataFrame:
    """落盘前把整数 float 单元格转 int，避免 CSV 文本出现 ".0" 尾缀。

    上游 normalize_number 恒返 float（"2321" → 2321.0），直接 to_csv 会写成 "2321.0"；
    非整数 float（363558.55）不受影响。追加路径会重读旧 CSV（旧版可能已带 ".0"），
    故转换必须在每次写入前做。
    """
    if df.empty:
        return df
    return df.apply(lambda col: col.map(_int_if_whole_float))


def save_companies(rows: list[dict], data_dir: Path) -> tuple[Path, Path]:
    """公司列表落盘：companies_latest.csv + A股上市公司列表_YYYY-MM-DD.xlsx。

    CSV/xlsx 均按 交易所、公司代码 排序；xlsx 含三 sheet：全部/上海(SSE)/深圳(SZSE)。
    整体覆盖式快照（不做追加），返回 (csv 路径, xlsx 路径)。
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    df = _strip_float_tail(
        pd.DataFrame(rows, columns=COMPANY_COLUMNS).sort_values(["交易所", "公司代码"]))
    csv_path = data_dir / COMPANIES_CSV
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    today = datetime.date.today().isoformat()
    xlsx_path = data_dir / f"A股上市公司列表_{today}.xlsx"
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="全部", index=False)
        df[df["交易所"] == "SSE"].to_excel(writer, sheet_name="上海", index=False)
        df[df["交易所"] == "SZSE"].to_excel(writer, sheet_name="深圳", index=False)
    return csv_path, xlsx_path


def append_market_stats(new_rows: list[dict], data_dir: Path) -> Path:
    """市场统计幂等追加到 market_stats.csv。

    幂等键 日期+交易所+板块：同键新行覆盖旧行（keep='last'），其它键的旧行保留；
    落盘前按三键排序，CSV 为 utf-8-sig。返回 csv 路径。
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    csv_path = data_dir / MARKET_STATS_CSV
    old = pd.read_csv(csv_path) if csv_path.exists() else pd.DataFrame()
    new = pd.DataFrame(new_rows, columns=STATS_COLUMNS)
    merged = _strip_float_tail(
        pd.concat([old, new], ignore_index=True)
        .drop_duplicates(subset=STATS_KEYS, keep="last")
        .sort_values(STATS_KEYS)
    )
    merged.to_csv(csv_path, index=False, encoding="utf-8-sig")
    return csv_path
