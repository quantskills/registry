# 目录审核 / Catalog review — 2026-10-09

维护者：abgyjaguo。用户已要求对 19 项积压提案进行审核并推进合格项目。
公开目录从 214 增至 218 项：新增 4 项、更新 9 项已收录项目的版本，6 项保留整改。
逐项提交、决定及原因见 [审核记录](catalog-review-20261009.json)。

## 新增收录

- `agent-cross-market-event-radar`：跨市场公司事件看板与风险提示；保留作者的 draft 状态。
- `skill-backtest-etf`：ETF 时序与截面策略研究回测。
- `skill-factor-drift-monitor`：因子面板漂移、覆盖率和稳定性监控。
- `skill-fund-holding-xray`：ETF 成分券、基金持仓估算及风险报告。

收录只表示公开目录元数据经过审核，不代表认证、推荐、生产可用或收益承诺。
新增项目未获得旧模型评分，明确保留 `current_ranking_eligible: false`。
这不关闭评分：新评测候选检测继续包含这些项目，GPT-6 Sol/medium 的测量仍独立保存。
原有签名测量、评分、历史记录和推荐规则保留；仅重新绑定新目录快照。

## 暂缓与所需整改

- `skill-a-share-placement-discount-alpha`：补齐根声明、完整 GPLv3、英文 README 和运行入口。
- `skill-factor-calendar-formulas`：修正 Cursor 指向不存在目录的加载入口，补明确上游元数据与维护者署名；不采用其自声明 verified 身份。
- `skill-factor-health-monitor`、`skill-factor-rl-weighting`、`skill-trading-behavior-diagnostics`：补齐英文 README、Cursor/portable 入口及完整 GPLv3 文本。
- `agent-quantspace`：澄清新声明的 official 身份、许可证标识和 Hermes 可移植入口。保留既有审核版本；测试中的模拟凭据未作为真实泄漏处理。

## 验证边界

只读核验公开仓库准确提交、声明、双语文档、完整许可证、加载入口和支持文件；
使用既有安全规则进行静态扫描，保留 warning，未执行候选代码。
`skill-signal-portfolio-optimize` 沿用用户已批准且绑定准确提交的仿真误判例外。
没有新增推荐或公开端点，没有修改候选仓库、预算、重试、安全规则、可见性或许可证。

复核命令（Registry 根目录）：

```text
python -m unittest tests.test_unranked_catalog_listing tests.test_evaluation_projection -v
python scripts/verify_catalog_artifacts.py --readme README.md --readme README.en.md --expected-contract-mode enforce
python scripts/verify_public_evaluations.py
node scripts/validate-registry.mjs --contract-mode enforce
```

## English

Owner-authorized review of 19 proposals adds four community listings and updates
nine existing revisions; six remain deferred with actionable reasons above and
in the JSON review. The public catalog grows from 214 to 218 entries. Listing
does not certify quality, grant recommendation or publish an execution endpoint.
New listings remain outside the established model ranking without invented
scores; evaluation candidate detection still includes them. Historical signed
measurements and model cohorts remain intact. Candidate repositories were read
only and no candidate code or model request was executed.
