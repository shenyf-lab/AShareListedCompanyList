# src/ashare/main.py
"""CLI 编排入口：公司列表快照 / 市场统计追加 / 全量。

用法：
    python -m src.ashare.main companies [--data-dir PATH]
    python -m src.ashare.main stats [--date YYYY-MM-DD] [--data-dir PATH]
    python -m src.ashare.main all [--date YYYY-MM-DD] [--data-dir PATH]

退出码：0 正常（含"无数据跳过"），1 失败（未捕获异常）。
"""
import argparse
import datetime
import sys
from pathlib import Path

from .httpclient import HttpClient
from .sse import enrich_sse_details, fetch_sse_companies, fetch_sse_market_stats
from .storage import append_market_stats, save_companies
from .szse import fetch_szse_companies, fetch_szse_market_stats


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


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--date", default=datetime.date.today().isoformat(),
                        help="统计日期 YYYY-MM-DD，默认今天（仅 stats/all 使用）")
    common.add_argument("--data-dir", default="data", help="输出目录，默认 ./data")
    parser = argparse.ArgumentParser(
        prog="python -m src.ashare.main",
        description="沪深 A 股上市公司列表与市场统计抓取",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("companies", parents=[common],
                   help="全量公司列表（CSV + xlsx 覆盖快照，沪市含详情补齐）")
    sub.add_parser("stats", parents=[common],
                   help="指定日期市场统计（默认今天，幂等追加）")
    sub.add_parser("all", parents=[common], help="companies + stats")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI 入口：返回进程退出码（0 正常 / 1 失败）。"""
    args = _parse_args(argv)
    try:
        if args.command == "companies":
            return _run_companies(args)
        if args.command == "stats":
            return _run_stats(args)
        _run_companies(args)  # all：先公司后统计，任一异常 → 打印并返回 1
        return _run_stats(args)
    except Exception as exc:  # noqa: BLE001 —— CLI 边界统一兜底
        print(f"执行失败：{exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
