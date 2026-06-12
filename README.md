# QUANTSKILLS Registry

QUANTSKILLS skills and agents 的公开目录。这里给用户和 AI agent 快速发现“有哪些可用资产、每个资产做什么、如何读取机器索引”。

English version is below.

## 快速开始

- [浏览资产目录](INDEX.md)：按分类查看可用的 skills 和 agents。
- [读取机器索引](registry.json)：给网站、工具或自动化系统消费的公开 JSON。
- [给 AI agent 使用](llms.txt)：轻量级 LLM/agent 发现索引。
- [读取 marketplace 元数据](.claude-plugin/marketplace.json)：Claude Code 兼容的 marketplace feed。

## 这个仓库是什么

`quantskills/registry` 是 QUANTSKILLS 生态的公开展示层。它回答：

- 目前有哪些公开的 skill / agent？
- 每个资产适合解决什么问题？
- 它属于哪个分类，有哪些 tags？
- 它声明支持哪些 agent 平台？
- 它的公开验证等级是什么？

这个仓库不是内部问题清单。详细审计、修复建议和人工复核记录不放在这里，后续由维护者在本地通过维护 Skill 或本地脚本处理。

## 给用户

大多数用户只需要看 [INDEX.md](INDEX.md)。

公开目录只展示适合被外部发现的资产。被隔离的项目、内部检查细节、具体问题列表不会进入这个公开层。

## 给工具和 AI agent

| 文件 | 用途 |
| --- | --- |
| [`registry.json`](registry.json) | 公开、机器可读的资产索引 |
| [`INDEX.md`](INDEX.md) | 人类可读的资产目录 |
| [`llms.txt`](llms.txt) | LLM / agent 发现索引 |
| [`.claude-plugin/marketplace.json`](.claude-plugin/marketplace.json) | Marketplace feed |

公开的 `registry.json` 不包含 `health_items`、内部扫描失败详情或本地审计备注。

## 资产声明方式

- `skill-*` 仓库使用 `SKILL.md`。
- `agent-*` 仓库使用 `AGENT.md`。
- 资产元数据写在 `quantSkills` frontmatter 中。

## 维护者入口

- [Maintainer guide](docs/MAINTAINER_GUIDE.md)
- [Security setup](docs/SECURITY_SETUP_zh.md)
- [Website integration](docs/SITE_INTEGRATION_zh.md)
- [Frontmatter schema](schema/frontmatter.schema.json)
- [Registry schema](schema/registry.schema.json)

---

## English

QUANTSKILLS Registry is the public directory for QUANTSKILLS skills and agents. It helps users, websites, tools, and AI agents discover what assets exist and what each asset is for.

## Start Here

- [Browse the directory](INDEX.md): view available skills and agents by category.
- [Use the machine registry](registry.json): consume the public JSON index.
- [Use with agents](llms.txt): lightweight index for LLM and agent discovery.
- [Install marketplace metadata](.claude-plugin/marketplace.json): Claude Code-compatible marketplace feed.

## What This Repository Is

`quantskills/registry` is the public display layer for the QUANTSKILLS ecosystem. It answers:

- What public skills and agents exist?
- What is each asset for?
- Which category and tags does it declare?
- Which agent platforms does it support?
- What public validation level does it declare?

This repository is not an internal issue list. Detailed audits, remediation notes, and human-review records are handled locally by maintainers through a maintenance Skill or local scripts.

## For Users

Most users only need [INDEX.md](INDEX.md).

The generated directory includes public `skill-*` and `agent-*` assets that are safe to display. Quarantined assets, internal check details, and specific issue lists are filtered out of this public layer.

## For Tools And AI Agents

| File | Purpose |
| --- | --- |
| [`registry.json`](registry.json) | Public machine-readable asset index |
| [`INDEX.md`](INDEX.md) | Human-readable directory |
| [`llms.txt`](llms.txt) | LLM / agent discovery index |
| [`.claude-plugin/marketplace.json`](.claude-plugin/marketplace.json) | Marketplace feed |

Public `registry.json` intentionally does not include `health_items`, internal scan failures, or local audit notes.

## Asset Declarations

- `skill-*` repositories use `SKILL.md`.
- `agent-*` repositories use `AGENT.md`.
- Asset metadata is declared in `quantSkills` frontmatter.

## Maintainers

- [Maintainer guide](docs/MAINTAINER_GUIDE.md)
- [Security setup](docs/SECURITY_SETUP_zh.md)
- [Website integration](docs/SITE_INTEGRATION_zh.md)
- [Frontmatter schema](schema/frontmatter.schema.json)
- [Registry schema](schema/registry.schema.json)

## License

GPL-3.0
