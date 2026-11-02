# src/ashare/clean.py
"""数据清洗纯函数：HTML 剥壳、占位符清空、千分位数字、日期归一、ASCII 提取、行数护栏。

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


def guard_row_count(row_count: int, reported_total: int, label: str) -> None:
    """列表行数护栏：空列表或行数远低于服务端自报总数时抛 RuntimeError。

    覆盖式快照落盘前的最后防线（接口结构变更 → 合法 JSON 但无/残数据）：
    - 行数为 0 → 抛错
    - 服务端自报总数 > 0 时：行数 < 95% 自报总数 → 抛错
    - 自报总数缺失（0）时：行数 < 500 的绝对下限 → 抛错
    """
    if row_count == 0:
        raise RuntimeError(f"{label}抓取到 0 行，疑似接口结构变更")
    if reported_total > 0:
        if row_count < reported_total * 0.95:
            raise RuntimeError(
                f"{label}仅抓到 {row_count} 行，远低于服务端自报总数 {reported_total}")
    elif row_count < 500:
        raise RuntimeError(f"{label}仅抓到 {row_count} 行，低于 500 行下限（服务端未报总数）")
