# tests/test_storage.py
import pandas as pd
from src.ashare.storage import save_companies, append_market_stats, STATS_COLUMNS

def company_row(code="000001"):
    return {"交易所": "SZSE", "公司代码": code, "A股代码": code, "A股简称": "平安银行",
            "公司全称": "", "英文全称": "", "板块": "主板", "A股上市日期": "1991-04-03",
            "A股总股本(股)": 194.05e8, "A股流通股本(股)": 194.05e8, "B股代码": "", "B股上市日期": "",
            "省份": "", "所属行业": "J 金融业", "上市状态": "上市", "退市日期": "",
            "注册地址": "", "公司网址": "", "抓取日期": "2026-11-02"}

def test_save_companies_csv_and_xlsx(tmp_path):
    csv, xlsx = save_companies([company_row("000002"), company_row("000001")], tmp_path)
    df = pd.read_csv(csv, dtype={"公司代码": str})
    assert list(df["公司代码"]) == ["000001", "000002"]          # 排序
    with open(csv, "rb") as f: assert f.read(3) == b"\xef\xbb\xbf"  # utf-8-sig BOM
    xf = pd.ExcelFile(xlsx)
    assert xf.sheet_names == ["全部", "上海", "深圳"]
    assert len(xf.parse("上海")) == 0 and len(xf.parse("深圳")) == 2

def test_save_companies_strips_float_tail(tmp_path):
    row = company_row()
    row["A股总股本(股)"] = 29352168000.0    # 整数值的 float，CSV 不应带 ".0"
    row["A股流通股本(股)"] = 29352168000.0
    csv, _ = save_companies([row], tmp_path)
    text = csv.read_text(encoding="utf-8-sig")
    assert "29352168000" in text and "29352168000.0" not in text

def stat_row(date="2026-10-30", ex="SSE", board="整体", pe=15.81):
    return {"日期": date, "交易所": ex, "板块": board, "上市公司数": 2321, "上市证券数": 2359,
            "总股本(亿股)": 51839.6, "流通股本(亿股)": 48756.65, "总市值(亿元)": 629609.47,
            "流通市值(亿元)": 566063.43, "平均市盈率": pe, "成交金额(亿元)": None,
            "平均股价(元)": None, "换手率(%)": None}

def test_append_market_stats_idempotent(tmp_path):
    append_market_stats([stat_row()], tmp_path)
    append_market_stats([stat_row(pe=16.0)], tmp_path)           # 同键重跑 → 覆盖
    df = pd.read_csv(tmp_path / "market_stats.csv")
    assert len(df) == 1 and df.iloc[0]["平均市盈率"] == 16.0

def test_append_market_stats_keeps_other_days(tmp_path):
    append_market_stats([stat_row()], tmp_path)
    append_market_stats([stat_row(date="2026-10-31", ex="SZSE", board="整体", pe=24.75)], tmp_path)
    df = pd.read_csv(tmp_path / "market_stats.csv")
    assert len(df) == 2 and list(df["日期"]) == ["2026-10-30", "2026-10-31"]

def test_append_market_stats_strips_float_tail(tmp_path):
    row = stat_row()
    row["上市公司数"] = 2321.0             # 整数值的 float → "2321"
    row["总市值(亿元)"] = 363558.55        # 非整数 float 保持原样
    append_market_stats([row], tmp_path)
    text = (tmp_path / "market_stats.csv").read_text(encoding="utf-8-sig")
    assert "2321" in text and "2321.0" not in text
    assert "363558.55" in text

def test_append_market_stats_rewrites_old_float_tail(tmp_path):
    """追加会重读旧 CSV：旧版写出的 "2321.0" 重写时必须去掉尾缀。"""
    append_market_stats([stat_row()], tmp_path)
    csv_path = tmp_path / "market_stats.csv"
    csv_path.write_text(csv_path.read_text(encoding="utf-8-sig").replace("2321,", "2321.0,"),
                        encoding="utf-8-sig")  # 模拟旧版代码写出的 ".0" 尾缀
    append_market_stats([stat_row(date="2026-10-31", ex="SZSE", board="整体")], tmp_path)
    text = csv_path.read_text(encoding="utf-8-sig")
    assert "2321" in text and "2321.0" not in text
