# quantskills Registry Auditor

> 组织的公开资产注册表:每晚只读扫描全部 `skill-*` 与 `agent-*` 仓库 -> 生成公开 registry、目录、llms.txt 与 marketplace 清单。详细审计报告不在本公开仓库保存。

## 工作原理

每个仓库的声明文件 frontmatter 是它的唯一元数据源: `skill-*` 使用 `SKILL.md`, `agent-*` 使用 `AGENT.md`。契约见 [`schema/frontmatter.schema.json`](schema/frontmatter.schema.json)。

流水线每晚执行:

1. 用只读 token 列出组织内全部 `skill-*` 与 `agent-*` 仓库
2. 浅克隆每个仓库
3. 运行 [`scripts/validate_skill.py`](scripts/validate_skill.py) 做确定性检查:
   - 必备文件
   - frontmatter 合法性
   - 文内引用路径是否真实存在
   - Git 大文件卫生
   - 轻量泄密形态扫描
   - trader 仓库免责声明硬门槛
   - Python 语法
   - `requires` 依赖是否存在
4. 生成健康分级:
   - `healthy`: 进入 registry、目录、llms.txt 与 marketplace 清单
   - `warning`: 进入公开 registry 与目录,但详细问题只进入私有审计仓库
   - `quarantined`: 不进入公开 registry,只进入私有审计仓库
5. 自动提交本仓库产物:
   - [`registry.json`](registry.json)
   - `INDEX.md`
   - `llms.txt`
   - `.claude-plugin/marketplace.json`

完整 `health_items`、quarantined 明细和人工复核清单由私有仓库 `quantskills/registry-audit` 保存。

## 安全边界

本仓库采用只读审计模型:

- 不修改任何 skill / agent 仓库
- 不开修复 PR
- 不改 GitHub topics / description / homepage
- 不在 skill / agent 仓库开、关、编辑 issue
- 不触发其他仓库的写操作
- 不公开详细审计报告
- 不做默认组织镜像备份

对 `skill-*` / `agent-*` 仓库只需要 Metadata read + Contents read。registry 仓库自己的 Actions `GITHUB_TOKEN` 只需要 Contents write,用于提交生成物。配置步骤见 [`docs/SECURITY_SETUP_zh.md`](docs/SECURITY_SETUP_zh.md)。

## 目录

```text
registry/
├── AGENT.md                          # 人工复核辅助说明
├── LICENSE                           # GPL-3.0
├── registry.json                     # 自动生成:公开机器可读注册表(不含 health_items)
├── INDEX.md                          # 自动生成:人类可读目录
├── llms.txt                          # 自动生成:agent 站点索引
├── .claude-plugin/marketplace.json   # 自动生成:Claude Code 插件市场
├── scripts/
│   ├── validate_skill.py             # skill / agent 确定性健康检查器
│   └── build_registry.py             # 只读扫描 -> 校验 -> 生成产物
├── schema/
│   ├── frontmatter.schema.json       # SKILL.md 元数据契约
│   └── registry.schema.json          # 注册表条目结构
├── docs/
│   ├── SECURITY_SETUP_zh.md          # 最小权限配置清单
│   ├── SITE_INTEGRATION_zh.md        # 网站侧拉取对接说明
│   └── templates/disclaimer_zh_en.md # trader 仓库标准免责声明文案
└── .github/workflows/
    └── nightly-scan.yml              # 每晚只读扫描主流水线
```

## 本地使用

```bash
pip install pyyaml requests
python scripts/validate_skill.py /path/to/skill-repo
GITHUB_TOKEN=xxx python scripts/build_registry.py --full
```

`GITHUB_TOKEN` 只需要读权限。如果只扫描公开仓库,也可以不传 token,但会受到 GitHub API 速率限制。

## License

GPL-3.0
