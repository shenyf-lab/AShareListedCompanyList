# tests/test_main.py
"""CLI 编排测试：monkeypatch main 模块上的 fetch 函数，验证编排与退出码。"""
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
