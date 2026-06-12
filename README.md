# QUANTSKILLS Registry

Public directory for QUANTSKILLS skills and agents.

## Start Here

- [Browse the directory](INDEX.md): see available skills and agents.
- [Use the machine registry](registry.json): consume the public JSON index.
- [Use with agents](llms.txt): lightweight index for LLM and agent discovery.
- [Install marketplace metadata](.claude-plugin/marketplace.json): Claude Code-compatible marketplace feed.

## What This Repository Is

This is the public display layer for the QUANTSKILLS ecosystem. It answers:

- What skills and agents exist?
- What is each asset for?
- Is it a `skill` or an `agent`?
- What validation level and maintainer type does it declare?

Detailed audit findings are not published here. Internal health reports live in the private `quantskills/registry-audit` repository.

## For Users

Most users only need [INDEX.md](INDEX.md).

The generated directory currently includes public `skill-*` and `agent-*` assets that are safe to display. Quarantined assets and detailed issue lists are filtered out of this public layer.

## For Tools

Use these stable files:

| File | Purpose |
| --- | --- |
| [`registry.json`](registry.json) | Public machine-readable asset index |
| [`INDEX.md`](INDEX.md) | Human-readable directory |
| [`llms.txt`](llms.txt) | LLM/agent discovery index |
| [`.claude-plugin/marketplace.json`](.claude-plugin/marketplace.json) | Marketplace feed |

Public `registry.json` intentionally does not include `health_items`, internal scan failures, or private audit notes.

## Asset Types

- `skill-*` repositories use `SKILL.md`.
- `agent-*` repositories use `AGENT.md`.
- Both declare metadata in `quantSkills` frontmatter.

## Maintainers

Maintenance docs and schemas are kept in this repository because the public index is generated from source:

- [Maintainer guide](docs/MAINTAINER_GUIDE.md)
- [Security setup](docs/SECURITY_SETUP_zh.md)
- [Website integration](docs/SITE_INTEGRATION_zh.md)
- [Frontmatter schema](schema/frontmatter.schema.json)
- [Registry schema](schema/registry.schema.json)

## License

GPL-3.0
