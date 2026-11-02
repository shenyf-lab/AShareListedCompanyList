# src/ashare/clean.py
"""数据清洗纯函数：HTML 剥壳、占位符清空、千分位数字、日期归一、ASCII 提取。

全部为纯函数（无 I/O、无网络、无状态），被各数据源解析任务共用。
"""
import html
import re
from datetime import datetime


def clean_html(text: str) -> str:
    """去除全部 HTML 标签与实体。"""
    return html.unescape(re.sub(r"<[^>]+>", "", text))


def empty_if_dash(value) -> str:
    """None/'-'/空白 -> ''，其余 strip 后返回。"""
    if value is None:
        return ""
    s = str(value).strip()
    return "" if s in ("", "-") else s


def normalize_number(value) -> float | None:
    """'363,558.55' -> 363558.55；'-'/''/None -> None；数字直通。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(",", "")
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def normalize_date(value) -> str:
    """20210525 / 2021-05-25 / 2021-05-25 00:00:00 -> '2021-05-25'；无法解析 -> ''。"""
    if value is None:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    try:
        return datetime.strptime(s, "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError:
        pass
    first = s.split()[0] if s.split() else ""
    try:
        return datetime.strptime(first, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def extract_ascii(text: str) -> str:
    """非 ASCII 可打印字符替换为空格后压缩连续空白（用于公司网址）。"""
    return " ".join(re.sub(r"[^ -~]", " ", text).split())
