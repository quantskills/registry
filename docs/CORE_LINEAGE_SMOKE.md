# Core lineage smoke scope

`schema/core-lineage/1.0.0/lineage.json` is a deterministic, synthetic
`schema-smoke-only` fixture. The Registry loader checks the committed artifact
schemas and SHA-256 digests (and fails closed on a missing or changed scope).

This fixture does not establish producer/consumer compatibility, business
dependencies, trading readiness, or any compatibility edge. Compatibility
edges are emitted only from validated asset interface declarations.

核心 lineage 仅用于可重复的 synthetic schema/hash 烟测，不代表业务闭环、生产就绪或
兼容边。业务兼容边只能来自经验证的资产接口声明。
