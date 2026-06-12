# quantskills Asset 目录

> 本文件由 build_registry.py 自动生成,请勿手工编辑。


## Skills / analyst

| Asset | 简介 | 验证级别 | 状态 | 标签 |
| --- | --- | --- | --- | --- |
| [skill-a-share-stock-dossier](https://github.com/quantskills/skill-a-share-stock-dossier) | 输入一个 A 股代码，输出一份可溯源的中文个股尽调报告：基本面、分红资本运作、股东行为、质押解禁减持风险、资金面，一次查清。 | L2 Runnable | stable | `a-share` `stock-dossier` `fundamentals` `due-diligence` `pandadata` |
| [skill-futures-deepview-analyst](https://github.com/quantskills/skill-futures-deepview-analyst) | 把"分析螺纹钢席位博弈""看豆粕期限结构和仓单"这类自然语言请求，转成 Pandadata 期货 DeepView 数据调用计划，输出事实与推断分离的中文研判报告。 | L2 Runnable | stable | `futures` `deepview` `basis` `term-structure` `pandadata` |
| [skill-gaetano-crux-capital-research-model](https://github.com/quantskills/skill-gaetano-crux-capital-research-model) | 基于公开资料复刻 Gaetano / Crux Capital 的研究方法：把公开 X 帖子、公开 Substack 页面、财报与技术论文，拆解成「光子堆栈定位 → chokepoint 识别 → 证据分级 → 催化与风险跟踪」的结构化研究模型。 | L1 Listed | stable | `ai-infrastructure` `photonics` `optical-networking` `physical-ai` `research-model` |
| [skill-index-valuation-rotation](https://github.com/quantskills/skill-index-valuation-rotation) | 指数估值与行业轮动分析：PE/PB 分位、估值温度、宽基定投参考、行业动量排名与轮动摘要。 | L2 Runnable | stable | `a-share` `index-valuation` `industry-rotation` `valuation-percentile` `pandadata` |
| [skill-options-vol-analyst](https://github.com/quantskills/skill-options-vol-analyst) | 期权波动率分析：期权链快照、隐含波动率、历史/实现波动率、IV 分位、期限结构、偏度与波动率溢价报告。 | L2 Runnable | stable | `options` `volatility` `implied-volatility` `derivatives` `pandadata` |
| [skill-serenity-research-model](https://github.com/quantskills/skill-serenity-research-model) | 从 Serenity（@aleabitoreddit）的公开 X 帖子里逆向研究逻辑：extract → clean → auto-review → evaluate → report 五段流水线，把帖子拆成最小信号单元，并用价格数据回看公开 call 的后续表现。 | L1 Listed | stable | `semiconductors` `ai` `public-posts` `research-model` `thesis-review` |
| [skill-stock-screener](https://github.com/quantskills/skill-stock-screener) | 自然语言 A 股选股：把分红、估值、质押、北向、行业概念、财务增长、股东变化等条件转成可追溯 Pandadata 筛选。 | L2 Runnable | stable | `a-share` `stock-screener` `fundamentals` `screening` `pandadata` |

## Skills / data-api

| Asset | 简介 | 验证级别 | 状态 | 标签 |
| --- | --- | --- | --- | --- |
| [skill-pandadata-api](https://github.com/quantskills/skill-pandadata-api) | 把自然语言数据需求，精准路由到正确的 pandadata API，并生成可直接运行的 Python 调用。 | L2 Runnable | stable | `pandadata` `panda-data` `market-data` `python-sdk` `api-reference` |
| [skill-pandadata-warehouse](https://github.com/quantskills/skill-pandadata-warehouse) | Pandadata 本地数据仓库：用 DuckDB 与 Parquet 缓存、增量刷新、查询和校验行情数据，减少重复 API 调用。 | L2 Runnable | stable | `pandadata` `warehouse` `duckdb` `parquet` `data-engineering` |

## Skills / factor

| Asset | 简介 | 验证级别 | 状态 | 标签 |
| --- | --- | --- | --- | --- |
| [skill-quant-factor-directional-alpha](https://github.com/quantskills/skill-quant-factor-directional-alpha) | 方向类因子库：296 个独立 OHLCV 因子 Skill，真实行情验证 296/296 全部通过。 | L3 Verified | stable | `alpha-factor` `directional` `ohlcv` `trend` `breakout` |
| [skill-quant-factor-risk-pattern-alpha](https://github.com/quantskills/skill-quant-factor-risk-pattern-alpha) | 风险状态与形态类因子库：288 个独立 OHLCV 因子 Skill，真实行情验证 288/288 全部通过。 | L3 Verified | stable | `alpha-factor` `risk-pattern` `ohlcv` `volatility` `drawdown` |
| [skill-quant-factor-volume-stat-alpha](https://github.com/quantskills/skill-quant-factor-volume-stat-alpha) | 量能、量价和统计排序类因子库：216 个独立 OHLCV 因子 Skill，真实行情验证 216/216 全部通过。 | L3 Verified | stable | `alpha-factor` `volume` `volume-price` `ranking` `statistics` |

## Skills / monitor

| Asset | 简介 | 验证级别 | 状态 | 标签 |
| --- | --- | --- | --- | --- |
| [skill-event-risk-alert](https://github.com/quantskills/skill-event-risk-alert) | A 股持仓和自选股事件风险预警：解禁、质押、减持、ST、业绩预告、审计意见等事件扫描与可追溯告警报告。 | L2 Runnable | stable | `a-share` `event-risk` `alerts` `monitoring` `pandadata` |
| [skill-macro-monitor](https://github.com/quantskills/skill-macro-monitor) | 把"查 CPI""本周有什么经济数据""钢铁行业景气度怎么样"这类请求，路由到正确的 Pandadata getmacro 接口，输出带数据时效标注的中文宏观分析与定期监控。 | L2 Runnable | stable | `macro` `industry` `calendar` `monitoring` `pandadata` |
| [skill-market-daily-review](https://github.com/quantskills/skill-market-daily-review) | 收盘后一句话生成 A 股当日复盘：指数与估值、市场宽度、行业概念热点、龙虎榜、大宗、两融、北向 —— 每个数字可溯源，支持定时自动生成。 | L2 Runnable | stable | `a-share` `daily-review` `market-breadth` `sentiment` `pandadata` |

## Skills / replication

| Asset | 简介 | 验证级别 | 状态 | 标签 |
| --- | --- | --- | --- | --- |
| [skill-paper-replication](https://github.com/quantskills/skill-paper-replication) | 把一篇量化金融论文（arXiv 或本地 PDF），变成一套可运行、可审计的复现实验：检索 → 提取 → 回测 → 图表 → 指标对照，全程框架无关。 | L2 Runnable | stable | `paper-replication` `quant-finance` `backtest` `research` `workflow` |
| [skill-quant-research-replication](https://github.com/quantskills/skill-quant-research-replication) | 搜索或接收量化论文、研报、PDF、网页、文本材料，产出一套完整的研究复现交付包：全文翻译 → 因子公式复现 → 有效性验证 → 策略代码 → 真实本地回测 → 交付摘要。 | L2 Runnable | stable | `research-replication` `quant-finance` `papers` `factors` `chinese-report` |
| [skill-report-replication](https://github.com/quantskills/skill-report-replication) | 把一篇量化研报、论文、PDF、网页或文本材料，转化为完整的研究复现交付包：全文翻译 → 因子公式复现 → 有效性验证 → 策略代码 → 真实本地回测 → 交付摘要。 | L2 Runnable | stable | `report-replication` `factor-research` `backtest` `html-report` `chinese` |

## Skills / tooling

| Asset | 简介 | 验证级别 | 状态 | 标签 |
| --- | --- | --- | --- | --- |
| [skill-quant-factor-skill-factory](https://github.com/quantskills/skill-quant-factor-skill-factory) | 不是因子库本身，而是继续生产因子库的工具：批量生成、验证和打包框架中立的 OHLCV 量化因子 Skill。 | L2 Runnable | stable | `factor-factory` `alpha` `ohlcv` `validation` `skill-generation` |
| [skill-ssquant-ai-trader](https://github.com/quantskills/skill-ssquant-ai-trader) | 你负责说话，AI 负责写代码、跑策略、盯盘、控风险。 | L2 Runnable | stable | `ssquant` `ai-trader` `strategy` `simnow` `automation` |
| [skill-ssquant-trader-generator](https://github.com/quantskills/skill-ssquant-trader-generator) | 说一次想法，得到一个可以随时加载的 AI 交易员。 | L2 Runnable | stable | `ssquant` `trader-generator` `ai-trader` `natural-language` `deployment` |
| [skill-x-trader-builder](https://github.com/quantskills/skill-x-trader-builder) | 把任意 X/Twitter 公开交易员的发帖历史，加工成 trader 专属的研究模型 Skill：init-run → 采集 → extract → auto-review → split → evaluate → template → report 九步流水线，从噪... | L2 Runnable | stable | `trader-skill` `research-model` `x-twitter` `skill-builder` `workflow` |
