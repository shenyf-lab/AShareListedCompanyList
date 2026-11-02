# src/ashare/main.py
"""CLI 编排入口：公司列表快照 / 市场统计追加 / 财报三表 / 全量。

用法：
    python -m src.ashare.main companies [--data-dir PATH]
    python -m src.ashare.main stats [--date YYYY-MM-DD] [--data-dir PATH]
    python -m src.ashare.main all [--date YYYY-MM-DD] [--data-dir PATH]
    python -m src.ashare.main financials [--symbols 600000,000001] [--years 10]
                                         [--statements income,balance,cashflow] [--data-dir PATH]

退出码：0 正常（含"无数据跳过"），1 失败（未捕获异常、护栏中止或 --symbols 全部未命中）。
"""
import argparse
import datetime
import sys
from pathlib import Path

import pandas as pd

from .httpclient import HttpClient
from .sina import STATEMENT_SOURCES, fetch_sina_statement, paper_code_for
from .sse import enrich_sse_details, fetch_sse_companies, fetch_sse_market_stats
from .storage import COMPANIES_CSV, append_financials, append_market_stats, save_companies
from .szse import fetch_szse_companies, fetch_szse_market_stats

_FINANCIALS_DEGRADE_THRESHOLD = 5   # 连续多少家公司抓取失败判定接口不可用
_FINANCIALS_MIN_DATA_RATIO = 0.5    # 有数据公司占比低于该值判定接口异常，不落盘


def _build_clients() -> tuple[HttpClient, HttpClient]:
    """构造沪深两个 client（模块级 fetch 函数的调用约定见各模块 docstring）。"""
    sse_client = HttpClient(referer="http://www.sse.com.cn/")
    szse_client = HttpClient(
        referer="https://www.szse.cn/",
        extra_headers={"x-requested-with": "XMLHttpRequest"},
    )
    return sse_client, szse_client


def _run_companies(args: argparse.Namespace) -> int:
    """公司列表：深+沪列表 → 沪市详情补齐 → 覆盖式快照落盘。"""
    sse_client, szse_client = _build_clients()
    szse_rows = fetch_szse_companies(szse_client)
    print(f"深交所上市公司：{len(szse_rows)} 家")
    sse_rows = fetch_sse_companies(sse_client)
    print(f"上交所上市公司：{len(sse_rows)} 家")
    sse_rows = enrich_sse_details(sse_client, sse_rows)
    rows = szse_rows + sse_rows
    csv_path, xlsx_path = save_companies(rows, Path(args.data_dir))
    print(f"共 {len(rows)} 家，已写入：")
    print(f"  {csv_path}")
    print(f"  {xlsx_path}")
    return 0


def _run_stats(args: argparse.Namespace) -> int:
    """市场统计：两所长表行 → 全空则跳过，否则幂等追加。"""
    sse_client, szse_client = _build_clients()
    data_dir = Path(args.data_dir)
    rows = fetch_sse_market_stats(sse_client, args.date, data_dir)
    rows += fetch_szse_market_stats(szse_client, args.date)
    if not rows:
        print("该日期无数据（可能为非交易日），未写入")
        return 0
    csv_path = append_market_stats(rows, data_dir)
    print(f"市场统计 {len(rows)} 行已追加：{csv_path}")
    return 0


def _select_financial_companies(args: argparse.Namespace, data_dir: Path) -> list[dict]:
    """companies_latest.csv -> 待抓取公司列表（交易所/A股代码/A股简称）。

    --symbols 给定则按 A股代码 过滤（清单中不存在的打印警告跳过），缺省取全部；
    返回 dict 列表，键：交易所 / A股代码 / A股简称。
    """
    listing = pd.read_csv(data_dir / COMPANIES_CSV, dtype=str,
                          keep_default_na=False, encoding="utf-8-sig")
    records = listing[["交易所", "A股代码", "A股简称"]].to_dict("records")
    if not args.symbols:
        return records
    by_code = {r["A股代码"]: r for r in records}
    selected: list[dict] = []
    for symbol in dict.fromkeys(s.strip() for s in args.symbols.split(",") if s.strip()):
        record = by_code.get(symbol)
        if record is None:
            print(f"警告：{symbol} 不在 companies_latest.csv 中，已跳过")
        else:
            selected.append(record)
    return selected


def _run_financials(args: argparse.Namespace) -> int:
    """财报三表：清单选公司 → 新浪年报/半年报 → 幂等追加三文件。

    - 单家失败打印代码与异常后继续；连续 5 家失败判定接口不可用，中止返回 1
    - 有数据（≥1 行）公司占比 < 50% 判定接口异常，中止且不写任何数据
    - --symbols 给定但全部未命中 → 无待抓取公司，返回 1（默认全清单为空仍返回 0）
    - 全部抓取完成后按报表幂等追加（代码+报告期 同键覆盖），简称取自清单
    """
    statements = [s.strip() for s in args.statements.split(",") if s.strip()]
    if not statements:
        raise ValueError(f"未指定报表（可选 {'/'.join(STATEMENT_SOURCES)}）")
    statements = list(dict.fromkeys(statements))  # 去重（income,income 只抓一次）
    invalid = [s for s in statements if s not in STATEMENT_SOURCES]
    if invalid:
        raise ValueError(f"未知报表 {','.join(invalid)}（可选 {'/'.join(STATEMENT_SOURCES)}）")
    if args.years < 1:
        raise ValueError(f"--years 需为正整数，当前为 {args.years}")

    data_dir = Path(args.data_dir)
    if not (data_dir / COMPANIES_CSV).exists():
        print("未找到 companies_latest.csv，请先运行: python -m src.ashare.main companies")
        return 1
    companies = _select_financial_companies(args, data_dir)
    if not companies:
        if args.symbols:  # --symbols 显式给出却全部未命中：手误当失败，防调用方误判成功
            print("--symbols 指定的代码均不在 companies_latest.csv 中，无待抓取公司")
            return 1
        print("无待抓取公司，未做任何请求")
        return 0
    print(f"待抓取 {len(companies)} 家公司 × {len(statements)} 张报表（近 {args.years} 年）")

    client = HttpClient(referer="https://finance.sina.com.cn/")
    buffer: dict[str, list[dict]] = {st: [] for st in statements}
    companies_with_data = 0
    consecutive_failures = 0
    failed_codes: list[str] = []
    for record in companies:
        code, name = record["A股代码"], record["A股简称"]
        row_count = 0
        try:
            paper_code = paper_code_for(record["交易所"], code)
            for statement in statements:
                rows = fetch_sina_statement(client, paper_code, statement, years=args.years)
                for row in rows:
                    row["简称"] = name
                buffer[statement].extend(rows)
                row_count += len(rows)
        except Exception as exc:  # noqa: BLE001 —— 单家失败继续，疑似接口故障时中止
            consecutive_failures += 1
            failed_codes.append(code)
            print(f"公司 {code} 财报抓取失败：{exc!r}")
            if consecutive_failures >= _FINANCIALS_DEGRADE_THRESHOLD:
                print(f"连续 {consecutive_failures} 家公司抓取失败，判定接口不可用，中止运行")
                return 1
            continue
        consecutive_failures = 0
        if row_count:
            companies_with_data += 1
        print(f"{code} {name}：{row_count} 行")
    if failed_codes:
        print(f"共 {len(failed_codes)} 家抓取失败")

    if companies_with_data < len(companies) * _FINANCIALS_MIN_DATA_RATIO:
        print(f"有数据公司 {companies_with_data}/{len(companies)} 家，低于 "
              f"{_FINANCIALS_MIN_DATA_RATIO:.0%}，疑似接口异常，未写入任何数据")
        return 1
    for statement in statements:
        if buffer[statement]:
            csv_path = append_financials(buffer[statement], data_dir, statement)
            print(f"{statement} {len(buffer[statement])} 行已写入：{csv_path}")
        else:
            print(f"{statement} 0 行，未写入")
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--date", default=datetime.date.today().isoformat(),
                        help="统计日期 YYYY-MM-DD，默认今天（仅 stats/all 使用）")
    common.add_argument("--data-dir", default="data", help="输出目录，默认 ./data")
    parser = argparse.ArgumentParser(
        prog="python -m src.ashare.main",
        description="沪深 A 股上市公司列表、市场统计与年报/半年报三大报表抓取",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("companies", parents=[common],
                   help="全量公司列表（CSV + xlsx 覆盖快照，沪市含详情补齐）")
    sub.add_parser("stats", parents=[common],
                   help="指定日期市场统计（默认今天，幂等追加）")
    sub.add_parser("all", parents=[common], help="companies + stats")
    financials = sub.add_parser(
        "financials", parents=[common],
        help="年报/半年报三大报表（新浪财经，幂等追加，需先运行 companies）")
    financials.add_argument("--symbols", default=None,
                            help="逗号分隔 A 股代码，默认 companies_latest.csv 全部公司")
    financials.add_argument("--years", type=int, default=10,
                            help="近 N 年报告期，默认 10")
    financials.add_argument("--statements", default="income,balance,cashflow",
                            help="逗号分隔报表（income/balance/cashflow），默认全部三表")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI 入口：返回进程退出码（0 正常 / 1 失败）。"""
    args = _parse_args(argv)
    try:
        if args.command == "companies":
            return _run_companies(args)
        if args.command == "stats":
            return _run_stats(args)
        if args.command == "financials":
            return _run_financials(args)
        _run_companies(args)  # all：先公司后统计，任一异常 → 打印并返回 1
        return _run_stats(args)
    except Exception as exc:  # noqa: BLE001 —— CLI 边界统一兜底
        print(f"执行失败：{exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
