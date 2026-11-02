# tests/test_main.py
"""CLI 编排测试：monkeypatch main 模块上的 fetch 函数，验证编排与退出码。"""
import pandas as pd

from src.ashare import main as main_mod
from src.ashare.main import main


def one_row(exchange):
    """单条公司行（19 个中文列全给最小合法值）。"""
    return {"交易所": exchange, "公司代码": "600000", "A股代码": "600000", "A股简称": "浦发银行",
            "公司全称": "上海浦东发展银行股份有限公司", "英文全称": "", "板块": "主板",
            "A股上市日期": "1999-11-10", "A股总股本(股)": 1.0, "A股流通股本(股)": 1.0,
            "B股代码": "", "B股上市日期": "", "省份": "上海", "所属行业": "货币金融服务业",
            "上市状态": "上市", "退市日期": "", "注册地址": "上海市中山东一路12号",
            "公司网址": "www.spdb.com.cn", "抓取日期": "2026-11-02"}


def sse_row(board="整体"):
    """沪市统计行（13 个 STATS_COLUMNS 键，深特有 3 列为 None）。"""
    return {"日期": "2026-10-30", "交易所": "SSE", "板块": board, "上市公司数": 2321,
            "上市证券数": 2359, "总股本(亿股)": 1.0, "流通股本(亿股)": 1.0,
            "总市值(亿元)": 1.0, "流通市值(亿元)": 1.0, "平均市盈率": 15.81,
            "成交金额(亿元)": None, "平均股价(元)": None, "换手率(%)": None}


def szse_row():
    """深市统计行（整体一行，13 键齐全）。"""
    return {"日期": "2026-10-30", "交易所": "SZSE", "板块": "整体", "上市公司数": 2905,
            "上市证券数": 2905, "总股本(亿股)": 2.0, "流通股本(亿股)": 2.0,
            "总市值(亿元)": 2.0, "流通市值(亿元)": 2.0, "平均市盈率": 24.75,
            "成交金额(亿元)": 3000.0, "平均股价(元)": 10.0, "换手率(%)": 1.0}


def test_stats_no_data_skips_and_exits_zero(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(main_mod, "fetch_szse_market_stats", lambda c, d: [])
    monkeypatch.setattr(main_mod, "fetch_sse_market_stats", lambda c, d, cd: [])
    rc = main(["stats", "--date", "2026-10-31", "--data-dir", str(tmp_path)])
    assert rc == 0
    assert "无数据" in capsys.readouterr().out
    assert not (tmp_path / "market_stats.csv").exists()


def test_stats_writes_rows(monkeypatch, tmp_path):
    monkeypatch.setattr(main_mod, "fetch_szse_market_stats", lambda c, d: [szse_row()])
    monkeypatch.setattr(main_mod, "fetch_sse_market_stats",
                        lambda c, d, cd: [sse_row(), sse_row("主板"), sse_row("科创板")])
    rc = main(["stats", "--date", "2026-10-30", "--data-dir", str(tmp_path)])
    assert rc == 0 and (tmp_path / "market_stats.csv").exists()


def test_companies_orchestrates(monkeypatch, tmp_path):
    called = {}
    monkeypatch.setattr(main_mod, "fetch_szse_companies",
                        lambda c: called.update(sz=1) or [one_row("SZSE")])
    monkeypatch.setattr(main_mod, "fetch_sse_companies",
                        lambda c: called.update(sse=1) or [one_row("SSE")])
    monkeypatch.setattr(main_mod, "enrich_sse_details",
                        lambda c, rows: called.update(enr=1) or rows)
    rc = main(["companies", "--data-dir", str(tmp_path)])
    assert rc == 0 and called == {"sz": 1, "sse": 1, "enr": 1}
    assert (tmp_path / "companies_latest.csv").exists()


def test_all_orchestrates_companies_then_stats(monkeypatch, tmp_path):
    monkeypatch.setattr(main_mod, "fetch_szse_companies", lambda c: [one_row("SZSE")])
    monkeypatch.setattr(main_mod, "fetch_sse_companies", lambda c: [one_row("SSE")])
    monkeypatch.setattr(main_mod, "enrich_sse_details", lambda c, rows: rows)
    monkeypatch.setattr(main_mod, "fetch_szse_market_stats", lambda c, d: [szse_row()])
    monkeypatch.setattr(main_mod, "fetch_sse_market_stats", lambda c, d, cd: [sse_row()])
    rc = main(["all", "--date", "2026-10-30", "--data-dir", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "companies_latest.csv").exists()
    assert (tmp_path / "market_stats.csv").exists()


def test_all_uncaught_exception_prints_and_returns_one(monkeypatch, tmp_path, capsys):
    def boom(client):
        raise RuntimeError("boom")
    monkeypatch.setattr(main_mod, "fetch_szse_companies", boom)
    rc = main(["all", "--data-dir", str(tmp_path)])
    assert rc == 1
    assert "boom" in capsys.readouterr().out
    assert not (tmp_path / "market_stats.csv").exists()


# ---------- financials ----------

def write_companies_csv(tmp_path, codes):
    """写最小 companies_latest.csv（financials 只消费 交易所/A股代码/A股简称 三列）。"""
    lines = ["交易所,A股代码,A股简称"]
    for code in codes:
        exchange = "SSE" if code.startswith("6") else "SZSE"
        lines.append(f"{exchange},{code},公司{code}")
    (tmp_path / "companies_latest.csv").write_text("\n".join(lines) + "\n", encoding="utf-8-sig")

def fin_row(code, period="2025-12-31"):
    """单条财报行（简称由 main 从清单注入，此处不含）。"""
    return {"代码": code, "报告期": period, "报告类型": "年报", "披露日": "2026-04-01",
            "是否审计": "是", "币种": "CNY", "营业收入": 100.0}

def test_financials_happy_path_writes_three_files(monkeypatch, tmp_path, capsys):
    write_companies_csv(tmp_path, ["600000", "000002"])
    monkeypatch.setattr(main_mod, "fetch_sina_statement",
                        lambda c, pc, st, years=10: [fin_row(pc[2:])])
    rc = main(["financials", "--symbols", "600000,000002", "--data-dir", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "已写入" in out and "income" in out and "cashflow" in out
    for st in ("income", "balance", "cashflow"):
        df = pd.read_csv(tmp_path / f"financials_{st}.csv", dtype={"代码": str})
        assert list(df["代码"]) == ["000002", "600000"]            # 排序
        assert set(df["简称"]) == {"公司000002", "公司600000"}     # 简称来自清单

def test_financials_missing_companies_csv_returns_one(tmp_path, capsys):
    rc = main(["financials", "--data-dir", str(tmp_path)])
    assert rc == 1
    out = capsys.readouterr().out
    assert "未找到 companies_latest.csv" in out and "companies" in out
    assert not (tmp_path / "financials_income.csv").exists()

def test_financials_invalid_statement_returns_one(tmp_path, capsys):
    write_companies_csv(tmp_path, ["600000"])
    rc = main(["financials", "--statements", "profit", "--data-dir", str(tmp_path)])
    assert rc == 1
    assert "profit" in capsys.readouterr().out
    assert not (tmp_path / "financials_income.csv").exists()

def test_financials_empty_statements_returns_one(tmp_path, capsys):
    write_companies_csv(tmp_path, ["600000"])
    rc = main(["financials", "--statements", " , ", "--data-dir", str(tmp_path)])
    assert rc == 1
    assert "未指定报表" in capsys.readouterr().out
    assert not (tmp_path / "financials_income.csv").exists()

def test_financials_unknown_symbol_warns_and_skips(monkeypatch, tmp_path, capsys):
    write_companies_csv(tmp_path, ["600000"])
    monkeypatch.setattr(main_mod, "fetch_sina_statement",
                        lambda c, pc, st, years=10: [fin_row(pc[2:])])
    rc = main(["financials", "--symbols", "600000,999999", "--data-dir", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "999999" in out and "跳过" in out
    df = pd.read_csv(tmp_path / "financials_income.csv", dtype={"代码": str})
    assert list(df["代码"]) == ["600000"]

def test_financials_company_failure_logged_and_continues(monkeypatch, tmp_path, capsys):
    write_companies_csv(tmp_path, ["600000", "000002"])
    def fake(client, paper_code, statement, years=10):
        if paper_code.endswith("600000"):
            raise RuntimeError("boom")
        return [fin_row(paper_code[2:])]
    monkeypatch.setattr(main_mod, "fetch_sina_statement", fake)
    rc = main(["financials", "--data-dir", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "600000" in out and "boom" in out
    assert "共 1 家抓取失败" in out
    df = pd.read_csv(tmp_path / "financials_income.csv", dtype={"代码": str})
    assert list(df["代码"]) == ["000002"]

def test_financials_five_consecutive_failures_abort(monkeypatch, tmp_path, capsys):
    write_companies_csv(tmp_path, [f"60000{i}" for i in range(1, 7)])  # 6 家
    def boom(client, paper_code, statement, years=10):
        raise RuntimeError("down")
    monkeypatch.setattr(main_mod, "fetch_sina_statement", boom)
    rc = main(["financials", "--data-dir", str(tmp_path)])
    assert rc == 1
    out = capsys.readouterr().out
    assert "接口不可用" in out
    assert out.count("财报抓取失败") == 5                # 第 5 家即中止，第 6 家未请求
    assert not (tmp_path / "financials_income.csv").exists()

def test_financials_consecutive_counter_resets_on_success(monkeypatch, tmp_path):
    """4 失败 + 9 成功 + 4 失败：从未连续 5 家 → 不中止；9/17 有数据过护栏。"""
    codes = [f"6000{i:02d}" for i in range(1, 18)]      # 600001..600017
    write_companies_csv(tmp_path, codes)
    fail = {f"6000{i:02d}" for i in (1, 2, 3, 4, 14, 15, 16, 17)}
    def fake(client, paper_code, statement, years=10):
        if paper_code[2:] in fail:
            raise RuntimeError("flaky")
        return [fin_row(paper_code[2:])]
    monkeypatch.setattr(main_mod, "fetch_sina_statement", fake)
    rc = main(["financials", "--data-dir", str(tmp_path)])
    assert rc == 0
    df = pd.read_csv(tmp_path / "financials_income.csv", dtype={"代码": str})
    assert len(df) == 9                                   # 9 家成功公司的行都落盘

def test_financials_low_data_ratio_aborts_before_writing(monkeypatch, tmp_path, capsys):
    write_companies_csv(tmp_path, [f"60000{i}" for i in range(1, 5)])  # 4 家
    def fake(client, paper_code, statement, years=10):
        return [fin_row(paper_code[2:])] if paper_code.endswith("600001") else []
    monkeypatch.setattr(main_mod, "fetch_sina_statement", fake)
    rc = main(["financials", "--data-dir", str(tmp_path)])
    assert rc == 1
    out = capsys.readouterr().out
    assert "50%" in out and "未写入" in out
    assert not any((tmp_path / f"financials_{st}.csv").exists()
                   for st in ("income", "balance", "cashflow"))
