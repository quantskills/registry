# Catalog Contract v2

This is the operational contract for Registry declarations and generated catalog data. The normative sources are [`schema/frontmatter.schema.json`](../schema/frontmatter.schema.json) and [`schema/taxonomy.v1.json`](../schema/taxonomy.v1.json); declarations use `schema_version: 2.0.0`.

## Taxonomy and runtimes

The taxonomy has exactly 10 primary categories, 61 second-level subcategories (listed authoritatively in [`taxonomy.v1.json`](../schema/taxonomy.v1.json)), 14 workflow stages, and five workflow display groups.

| ID | Category |
|---|---|
| 01 | Data APIs & Warehouse |
| 02 | Factor R&D Toolbox |
| 03 | Market & Instrument Analysis |
| 04 | Risk Monitoring & Alerts |
| 05 | Backtesting & Trading |
| 06 | Research Models & Replication |
| 07 | Research Validation & Quality |
| 08 | Information Search & Knowledge Analysis |
| 09 | Quant Agents & Automation |
| 10 | Infrastructure & Templates |

Machine stage values are `data-ingestion`, `data-quality`, `feature-engineering`, `factor-generation`, `factor-screening`, `modeling`, `portfolio-construction`, `backtesting`, `evaluation`, `risk`, `monitoring`, `execution`, `reporting`, and `orchestration`. The five display groups are `data-foundation`, `research-signal`, `portfolio-validation`, `monitoring-trading`, and `orchestration`.

A completed Skill or Agent declares all five runtimes: `cursor`, `claude-code`, `codex`, `hermes`, and `openclaw`.

## Declaration fields

`catalog` declares one category and matching subcategory; `workflow` declares a `primary_stage` included in its unique `workflow_stages`. `summary_zh` and `summary_en` are one-line, truthful bilingual display summaries. `status` is `draft`, `active`, `stable`, or `deprecated`; `validation_level` is `listed`, `runnable`, or `verified`; `maintainer` identifies the responsible person or team and `maintainer_type` is `official` or `community`.

`interface` describes machine-facing exchange. The following fenced block is a complete copy-ready v2 declaration:

<!-- catalog-declaration-example:start -->
```yaml
name: skill-factor-grouped-wrapper
description: A structured wrapper that ranks candidate factors from market data and returns evaluation-ready outputs for quantitative research workflows.
quantSkills:
  schema_version: 2.0.0
  organization: quantskills
  organization_url: https://github.com/quantskills
  repository: skill-factor-grouped-wrapper
  repository_url: https://github.com/quantskills/skill-factor-grouped-wrapper
  project_type: skill
  license: GPL-3.0-only
  maintainer: abgyjaguo
  catalog: {category: "02", subcategory: 02.factor-selection}
  workflow: {primary_stage: factor-screening, workflow_stages: [factor-screening, evaluation]}
  summary_zh: 用于因子筛选与评估的结构化工作流。
  summary_en: Structured workflow for factor screening and evaluation.
  status: active
  validation_level: listed
  maintainer_type: community
  platforms: [cursor, claude-code, codex, hermes, openclaw]
  interface:
    mode: structured
    envelope: {name: quantskills-envelope, version: 1.0.0}
    inputs: [{profile: factor-panel, version_range: ">=1.0.0 <2.0.0", required: true}]
    outputs: [{profile: evaluation-result, version: 1.0.0}]
    adapters: [factor-ranking]
  tags: [factor-selection]
```
<!-- catalog-declaration-example:end -->

The modes are `structured`, `hybrid`, `natural-language`, and `not-applicable`. Structured/hybrid assets identify the Envelope as `{name: quantskills-envelope, version: 1.0.0}`, use input Profile semver ranges and exact output Profile versions, and declare `adapters`. `qsh-form` is optional and independent of this contract. For `not-applicable`, the only reasons are `natural-language-only`, `report-only`, and `orchestration-only`.

GitHub's `summary_zh｜summary_en` description is generated only after validation; it is never an unchecked source of either summary.

## Migration, outputs, and release safety

`audit` retains legacy assets and reports structured pending/warnings. `enforce` rejects incomplete, invalid, fallback, or migration-marker data. Unknown assets are never silently mapped to category 07, category 08, or `uncategorized`; `unknown` and `待迁移` cannot pass enforce.

`catalog.snapshot.json` is the complete deterministic catalog: it carries assets, organization resources, Profiles, adapters, and compatibility edges. `registry.json` is its backward-compatible array projection. Every projected row shares the snapshot's `snapshot_id`. Resources are organization infrastructure, not Skill/Agent assets.

Run migration in audit mode first; correct declarations and fixed fixtures; then build and validate enforce mode. Only an enforce-clean snapshot can be published. This foundation task does not migrate all 158 repositories and does not write remote repository metadata.
