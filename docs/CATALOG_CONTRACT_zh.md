# Catalog Contract v2（目录契约）

本文是 Registry 声明与生成目录的操作契约。权威来源是 [`schema/frontmatter.schema.json`](../schema/frontmatter.schema.json) 和 [`schema/taxonomy.v1.json`](../schema/taxonomy.v1.json)；声明使用 `schema_version: 2.0.0`。

## 分类、流程与运行时

分类体系恰有 10 个一级分类、61 个二级分类（完整清单以 [`taxonomy.v1.json`](../schema/taxonomy.v1.json) 为准）、14 个工作流阶段和 five workflow display groups（五个工作流展示组）。

| ID | 一级分类 |
|---|---|
| 01 | 数据接口与数据仓库 / Data APIs & Warehouse |
| 02 | 因子研发工具箱 / Factor R&D Toolbox |
| 03 | 市场与标的分析 / Market & Instrument Analysis |
| 04 | 风险监控与预警 / Risk Monitoring & Alerts |
| 05 | 策略回测与交易 / Backtesting & Trading |
| 06 | 投研模型与研究复现 / Research Models & Replication |
| 07 | 研究验证与质量 / Research Validation & Quality |
| 08 | 资讯搜索与知识分析 / Information Search & Knowledge Analysis |
| 09 | 量化智能体与自动化 / Quant Agents & Automation |
| 10 | 基础设施与模板 / Infrastructure & Templates |

14 个机器阶段值为 `data-ingestion`、`data-quality`、`feature-engineering`、`factor-generation`、`factor-screening`、`modeling`、`portfolio-construction`、`backtesting`、`evaluation`、`risk`、`monitoring`、`execution`、`reporting`、`orchestration`。五个展示组是 `data-foundation`、`research-signal`、`portfolio-validation`、`monitoring-trading`、`orchestration`。

完成的 Skill 或 Agent 必须声明五个运行时：`cursor`、`claude-code`、`codex`、`hermes`、`openclaw`。

## 声明字段

`catalog` 声明一个一级分类和与之匹配的二级分类；`workflow` 的 `primary_stage` 必须出现在去重后的 `workflow_stages` 中。`summary_zh` 与 `summary_en` 是单行、真实的双语展示摘要。`status` 可为 `draft`、`active`、`stable`、`deprecated`；`validation_level` 可为 `listed`、`runnable`、`verified`；`maintainer` 标识责任人或团队，`maintainer_type` 可为 `official` 或 `community`。

`interface` 描述机器间接口，例如：

```yaml
catalog: {category: "02", subcategory: "02.factor-evaluation"}
workflow: {primary_stage: evaluation, workflow_stages: [factor-screening, evaluation]}
summary_zh: 因子评估结果的可复现实验流程。
summary_en: Reproducible evaluation workflow for factor results.
interface:
  mode: structured
  envelope: {input: ">=1.0.0 <2.0.0", output: "1.0.0"}
  inputs: [{profile: factor-panel, version_range: ">=1.0.0 <2.0.0", required: true}]
  outputs: [{profile: evaluation-result, version: "1.0.0"}]
```

四种模式是 `structured`、`hybrid`、`natural-language`、`not-applicable`。structured/hybrid 的 Envelope/Profile 使用输入 semver 范围和精确输出版本；`qsh-form` 可选且独立于本契约。`not-applicable` 仅允许三种原因：`natural-language-only`、`report-only`、`orchestration-only`。

GitHub 描述 `summary_zh｜summary_en` 仅在验证后生成，绝不作为未经验证的摘要来源。

## 迁移、产物与发布安全

`audit` 保留旧资产可见性并报告结构化 pending/warnings；`enforce` 拒绝不完整、无效、fallback 或迁移标记数据。未知资产不得静默 fallback 到分类 07、08 或 `uncategorized`；`unknown` 和 `待迁移` 均不能通过 enforce。

完整的确定性目录是 `catalog.snapshot.json`：其中含资产、组织 resources、Profiles、adapters 和 compatibility edges。向后兼容的数组投影是 `registry.json`，每一行共享该快照的 `snapshot_id`。resources 是组织基础设施，不是 Skill/Agent 资产。

先以 audit 迁移，再修复声明和固定输入，最后构建并验证 enforce；只有 enforce-clean 快照可以发布。本 foundation task 不包含全组织 158 个仓库迁移，也不写入远程仓库元数据。
