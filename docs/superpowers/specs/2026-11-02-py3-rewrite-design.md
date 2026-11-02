# AShareListedCompanyList Python 3 重写设计

日期：2026-11-02
状态：待批准

## 一、意图与背景

原项目（2016-2018）用 Python 2 抓取沪深 A 股上市公司信息入 MySQL 再导 Excel，因 Python 2 EOL 和两所官网改版已不可运行。本次重写目标：

- Python 2 → Python 3
- HTTP 层统一为 requests（废弃 urllib/urllib2/mechanize 混用）
- 适配沪深交易所 2026 年新版网站接口
- 废弃 MySQL 存储，改为本地 CSV/Excel 文件（数据量小、快照性质，文件存储足够；同时消除明文数据库密码问题）

数据范围（与用户确认）：
1. **公司列表**（全量快照）：字段方案 A+——上交所列表接口 + 逐家详情接口补字段；深交所用列表接口字段
2. **市场统计**（按日追加）：沪深每日市场总貌指标

## 二、目标

- 一条命令抓取沪深全部 A 股上市公司列表，输出统一字段的 CSV + Excel
- 一条命令抓取指定日期（默认当日）的沪深市场统计指标，追加到 CSV，同日重跑幂等
- 全量公司列表运行时长 ≤ 45 分钟（含沪市逐家详情）
- 部分接口/单家公司失败不中断整体，失败处留空并记录日志

## 三、非目标（明确不做）

- 年报/半年报等定期报告的财务数据（数字在 PDF 内，用户自行另想办法）
- PDF 下载与解析
- 第三方数据源（巨潮资讯等）
- B 股股本明细（两所接口均不提供）
- 城市字段（两所接口均无，老项目中本就是省份复制值）
- 定时调度（用户手动运行）

## 四、约束

- 目标环境：Windows 11，Python 3.10+
- 交易所接口无鉴权但有基础反爬：需带浏览器 UA 与 Referer；请求间隔保持 ~0.3s（沿用老项目节奏）
- 上交所 `query.sse.com.cn` 域名接口为 jsonp 包装（`jsonpCallbackXXX(...)`），需剥壳后 json 解析；深交所为纯 JSON
- 深交所接口需要 `x-requested-with: XMLHttpRequest` 头（浏览器实测）
- CSV 必须用 `utf-8-sig` 编码（否则 Excel 打开中文乱码）

## 五、数据链路设计

### 5.1 上交所公司列表

**列表接口**（已验证）：
```
GET https://query.sse.com.cn/sseQuery/commonQuery.do
    ?jsonCallBack=jsonpCallback{rand}
    &STOCK_TYPE={板块}&REG_PROVINCE=&CSRC_CODE=&STOCK_CODE=
    &sqlId=COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L
    &COMPANY_STATUS=2,4,5,7,8
    &type=inParams&isPagination=true
    &pageHelp.cacheSize=1&pageHelp.beginPage={n}&pageHelp.pageSize=25
    &pageHelp.pageNo={n}&pageHelp.endPage={n}&_={ts}
```
- 每页 25 条，`pageHelp` 元数据里有总页数
- STOCK_TYPE=1 为主板 A 股；科创板需另一 STOCK_TYPE 值（实现时从页面下拉实测确认，预计 5 或类似）——**必须覆盖主板 A + 科创板**，B 股不做
- **快照口径（评审决定）**：当前在市公司，含 ST/\*ST/暂停上市等全部在市状态，**不含退市**（COMPANY_STATUS=2,4,5,7,8 即页面"股票列表"的在市状态集合；退市公司在上交所单独的"暂停/终止上市"页面，不在本工具范围）。与老项目"剔除摘牌"行为一致。STATE_CODE 词表实现时按页面状态描述对照确认
- 关键返回字段：COMPANY_CODE、COMPANY_ABBR、FULL_NAME、FULL_NAME_IN_ENGLISH、A_STOCK_CODE、B_STOCK_CODE、LIST_DATE（yyyymmdd）、DELIST_DATE、AREA_NAME_DESC（省份）、CSRC_CODE_DESC（行业）、STATE_CODE、LIST_BOARD

**详情接口**（A+ 增补，路径为老项目同款，存活与否实现时验证；失败则整体降级为方案 A 并提示用户）：
- 公司概况：`commonQuery.do?sqlId=COMMON_SSE_ZQPZ_GP_GPLB_C&productid={code}` → 注册地址（COMPANY_ADDRESS）、公司网址（WWW_ADDRESS）
- B 股上市日期：`sqlId=COMMON_SSE_ZQPZ_GP_GPLB_BGSSR_C` → LISTINGDATEB（仅有 B 股代码的公司才请求）
- 股本结构：`query.sse.com.cn/security/stock/queryCompanyStockStruct.do?companyCode={code}` → A股总股本/流通股本
- 若老路径 404，尝试 `/sseQuery/commonQuery.do` 新路径

### 5.2 深交所公司列表

**列表接口**（已验证）：
```
GET https://www.szse.cn/api/report/ShowReport/data
    ?SHOWTYPE=JSON&CATALOGID=1110&PAGENO={n}&random={rand}
```
- 目录 ID 仍是 1110（A 股列表，tab1），2905 家、每页 20 条、146 页
- 分页参数名实现时实测（PAGENO 或随机 TABKEY 组合）
- 返回字段：板块 bk、A股代码 agdm、A股简称 agjc（**含 HTML 链接，需正则清洗**）、上市日期 agssrq、A股总股本 agzgb（亿股）、A股流通股本 agltgb（亿股）、所属行业 sshymc、尚未盈利 ylbz、表决权差异 sfjybjqcy、协议控制架构 gskzjglx
- 只抓 A 股 tab（老项目同样只入 A 股）

### 5.3 市场统计

**深交所**（已验证）：
```
GET https://www.szse.cn/api/report/ShowReport/data
    ?SHOWTYPE=JSON&CATALOGID=1803_after&txtQueryDate={YYYY-MM-DD}&random={rand}
```
- 返回数组第一个元素为"深圳市场"总貌（tab1）：上市公司数、上市证券数、总股本、流通股本、总市值、流通市值、成交金额、平均股价、平均市盈率、平均换手率（含深证成指等指数行，取指标行）
- 主板/创业板 tab 数据为空，只取深圳市场整体

**上交所**：
```
GET https://query.sse.com.cn/commonExcelDd.do
    ?sqlId=COMMON_SSE_SJ_GPSJ_GPSJZM_TJSJ_L
    &PRODUCT_NAME=股票,主板,科创板&type=inParams&TRADE_DATE={YYYY-MM-DD}
```
- 直接下载 xlsx（页面"下载"按钮同款），pandas 读取
- 若该接口不可用，备选：解析统计页服务端渲染 HTML（`/market/stockdata/statistic/`）
- 指标：上市公司数、上市股票数、总股本、流通股本、总市值、流通市值、平均市盈率（股票总体 + 主板 + 科创板）

**统一输出**（market_stats.csv，**长表结构（用户已确认）**：一行 = 日期 × 交易所 × 板块）：
`日期, 交易所, 板块, 上市公司数, 上市证券数(股票数), 总股本, 流通股本, 总市值, 流通市值, 平均市盈率, [深交所特有: 成交金额/平均股价/换手率]`
- 沪市每天 3 行（整体/主板/科创板），深市每天 1 行（整体）
- **幂等键**：日期 + 交易所 + 板块，同键重跑覆盖该行（读入-去重-追加-写回）
- **单位（评审决定）**：股本统一"亿股"、市值/成交金额统一"亿元"（两所原生口径即如此，无需换算）；平均股价"元"、市盈率"倍"、换手率"%"
- 数值带千分位逗号的清洗为数值；某板块无此指标（如沪主板行无"上市公司数"）留空
- **空数据（评审决定）**：目标日期无数据（非交易日/接口为空）时**跳过写行并打印提示**，已存在的行绝不被空数据覆盖

## 六、统一公司列表字段（companies.csv）

| 列 | 沪来源 | 深来源 |
|---|---|---|
| 交易所 | SSE | SZSE |
| 公司代码 | COMPANY_CODE | agdm |
| A股代码 | A_STOCK_CODE | agdm |
| A股简称 | COMPANY_ABBR | agjc（清洗HTML） |
| 公司全称 | FULL_NAME | 空 |
| 英文全称 | FULL_NAME_IN_ENGLISH | 空 |
| 板块 | LIST_BOARD 映射（主板/科创板） | bk |
| A股上市日期 | LIST_DATE → YYYY-MM-DD | agssrq |
| A股总股本(股) | 详情接口 | agzgb×10^8 |
| A股流通股本(股) | 详情接口 | agltgb×10^8 |
| B股代码 | B_STOCK_CODE（'-' → 空） | 空 |
| B股上市日期 | 详情接口 | 空 |
| 省份 | AREA_NAME_DESC | 空 |
| 所属行业 | CSRC_CODE_DESC | sshymc |
| 上市状态 | STATE_CODE 映射 | '上市' |
| 退市日期 | DELIST_DATE | 空 |
| 注册地址 | 详情接口 | 空 |
| 公司网址 | 详情接口（清洗中文） | 空 |
| 抓取日期 | 运行日 | 运行日 |

注：沪深行业口径不同（沪=证监会行业描述、深=门类简称），列名统一为"所属行业"，口径差异在 README 说明。总股本单位统一为股。

## 七、存储设计

```
data/
  companies_latest.csv            # 最新全量快照（固定名，覆盖写）
  A股上市公司列表_YYYY-MM-DD.xlsx  # Excel 产物（带日期保留历史，多sheet：沪/深/全部）
  market_stats.csv                # 市场统计（追加式，按日期+交易所幂等）
```

## 八、代码结构

```
requirements.txt          # requests, pandas, openpyxl
src/ashare/
  __init__.py
  httpclient.py           # requests 封装：UA/Referer/限速/重试3次/jsonp剥壳
  sse.py                  # 上交所：列表分页、详情、统计
  szse.py                 # 深交所：列表分页、统计
  storage.py              # CSV(utf-8-sig)/xlsx 读写、幂等追加
  main.py                 # CLI 入口
```

CLI：
```
python -m src.ashare.main companies    # 全量公司列表（覆盖快照）
python -m src.ashare.main stats [--date 2026-11-02]   # 市场统计（默认今天）
python -m src.ashare.main all
```

**旧文件处置**：删除 `syf/`、`test/`、`settings.py`、`database.conf`、`listed_company.sql`、`A股上市公司列表2018-06-11.xlsx`（git 历史可追溯）；README 重写。

## 九、错误处理

- requests 超时/连接失败：重试 3 次，仍失败该页/该公司跳过并记日志
- 沪市详情接口整体不可用：降级为方案 A（列表字段），打印提示
- 单家公司详情失败：该家补齐字段留空，继续下一家
- stats 目标日期无数据（非交易日）：跳过写行、打印提示、正常退出（退出码 0），不触碰已有数据
- 数据清洗：千分位、全角空格、'-' 统一为空值、日期格式化

## 十、验收标准

1. `python -m src.ashare.main companies` 在干净环境跑通，companies_latest.csv 行数 ≈ 5200（深 ~2900 + 沪 ~2320，随时间浮动），xlsx 可打开且中文正常
2. 沪市行注册地址/网址/股本非空率 ≥ 95%（详情接口存活时）
3. `python -m src.ashare.main stats --date 2026-10-30` 写入 4 行（沪整体/沪主板/沪科创/深整体）；重跑行数不变（幂等）；非交易日日期跳过写行且不破坏已有数据
4. 全程无未捕获异常退出

## 十一、留给实现者的决定

- 上交所科创板 STOCK_TYPE 具体值（实测）
- 深交所列表分页参数名（实测）
- 沪市详情接口的准确路径与参数（实测，含降级路径）
- 上交所统计 Excel 的列布局（实测后映射）
- httpclient 重试的退避策略细节
