# financials 年报/半年报链路实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 py3-rewrite 分支上新增 `financials` 子命令：从新浪财报 API 抓取沪深 A 股公司的**年报与半年报**财务数据（三大报表、全科目），按"代码×报告期"幂等追加到本地 CSV。

**Architecture:** 复用现有五模块模式——新模块 `sina.py`（接口已在控制器会话实测验证：纯 GET JSON、无鉴权）、`storage.py` 加 `append_financials`、`main.py` 加子命令。公司清单从 `data/companies_latest.csv` 读取（交易所列映射 sh/sz 前缀拼 paperCode）。

**Tech Stack:** 同现有（requests/pandas/openpyxl），无新依赖。

**Spec:** 对话内已确认（2026-11-02）：接口 `quotes.sina.cn/cn/api/openapi.php/CompanyFinanceService.getFinanceReport2022`，参数 paperCode/source(lrb|fzb|llb)/type=0/page=1/num=1000；报告期后缀 1231=年报、0630=半年报（0331/0930 丢弃）；每期自带 publish_date/is_audit/rCurrency。

## Global Constraints

- 沪深市场前缀：SSE→sh、SZSE→sz（paperCode 如 sh600000/sz000002）
- 只保留年报（1231）与半年报（0630）报告期；`--years` 过滤（默认 10，报告期年份 ≥ 当前年-10+1）
- 失败语义（沿用终审修复后的标准）：单家失败打印公司+异常并继续；连续 5 家失败判定接口不可用中止退出 1；成功公司数 < 清单 50% 时中止退出 1（防雪崩护栏）
- companies_latest.csv 不存在 → 报错提示先运行 companies，退出 1
- CSV utf-8-sig；幂等键 代码+报告期，keep='last'
- commit：conventional + 中文 + `Co-Authored-By: Claude Code <noreply@anthropic.com>`
- 不改动既有 49 个测试的行为

## Task F1: 新浪财报模块

**Files:**
- Create: `src/ashare/sina.py`、`tests/fixtures/sina_lrb_sample.json`（从素材裁剪）
- Test: `tests/test_sina.py`

**Interfaces:**
- Consumes: `HttpClient.get_json`（Task 1；referer 用 `https://finance.sina.com.cn/`，无需额外头）
- Produces:
  - `SINA_FINANCE_URL = "https://quotes.sina.cn/cn/api/openapi.php/CompanyFinanceService.getFinanceReport2022"`
  - `STATEMENT_SOURCES = {"income": "lrb", "balance": "fzb", "cashflow": "llb"}`
  - `fetch_sina_statement(client, paper_code: str, statement: str, years: int = 10) -> list[dict]` — 返回行 dict 列表；每行 = {代码, 报告期(YYYY-MM-DD), 报告类型(年报|半年报), 披露日, 是否审计, 币种, **科目…}（科目为动态键，item_value 转 float，'-' → None）
  - `paper_code_for(exchange: str, code: str) -> str` — 'SSE'+'600000'→'sh600000'

**Steps:**
- [ ] 裁 fixture（素材见 sdd 工作区 fixtures-src/sina_*.json，含万科三表）：lrb 一份含 20260630/20251231 两年报期 + 至少 1 个季报期（驱动筛选断言）
- [ ] 失败测试：paper_code 映射；解析（报告期筛选只留年报/半年报、years 过滤、科目 float 化、'-'→None、元信息齐全）；fetch 用 FakeClient 分页拼接不需要（单页 num=1000）
- [ ] 实现 sina.py（解析纯函数 `_parse_statement(data: dict, code: str, years: int) -> list[dict]` 供直测；fetch 组装 params 调 get_json）
- [ ] `python -m pytest tests/ -v` 全绿（49 既有 + 新增）
- [ ] Commit: `feat: 新浪财报模块（年报/半年报三大报表抓取与解析）`

## Task F2: 存储集成、CLI 与冒烟

**Files:**
- Modify: `src/ashare/storage.py`、`src/ashare/main.py`、`README.md`
- Test: `tests/test_storage.py`、`tests/test_main.py`（追加）

**Interfaces:**
- Consumes: F1 全部；`pd.read_csv(companies_latest.csv, dtype=str)` 读清单（代码/简称/交易所列）
- Produces:
  - `append_financials(rows: list[dict], data_dir: Path, statement: str) -> Path` — 写 `data/financials_{income|balance|cashflow}.csv`；固定列（代码/简称/报告期/报告类型/披露日/是否审计/币种）+ 动态科目列并集；幂等键 代码+报告期
  - CLI：`python -m src.ashare.main financials [--symbols 600000,000001] [--years 10] [--statements income,balance,cashflow]`（默认全清单、三表）
  - 简称列从 companies_latest.csv 带入

**Steps:**
- [ ] 失败测试：append_financials 幂等（同代码同报告期覆盖、异公司共存、科目列并集）；main financials 编排（monkeypatch fetch；清单缺失退出 1；单家失败继续、连续 5 家中止、成功率 <50% 中止）
- [ ] 实现与集成；README 加 financials 命令与字段说明（全科目、报告类型口径、披露日）
- [ ] 全量 `python -m pytest tests/ -v` 绿
- [ ] 真实冒烟：`python -m src.ashare.main financials --symbols 000002,600000` — 三表写入、年报+半年报筛选正确、幂等重跑行数不变
- [ ] Commit: `feat: financials 子命令与三表存储（幂等追加）`
