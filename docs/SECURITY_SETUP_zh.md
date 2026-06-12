# 安全配置指南:只读审计版

本文是 `quantskills/registry` 与私有 `quantskills/registry-audit` 的最小权限配置清单。目标是让流水线只能检查和记录,不能修改任何 skill / agent 仓库,且不公开详细审计问题。

## 权限模型

### 1. skill / agent 仓库读取 token

创建一个专用 Fine-grained personal access token,存为 registry 仓库 secret:

```text
QS_READ_TOKEN
```

Repository access:

- 仅选择需要扫描的 `skill-*` / `agent-*` 仓库
- 或选择组织内全部仓库,但权限仍保持只读

权限只勾:

- Metadata: Read-only
- Contents: Read-only

不要勾:

- Contents: Read and write
- Pull requests
- Issues
- Administration
- Workflows
- Secrets
- Deployments
- Environments
- Delete / destructive 相关权限

### 2. registry / registry-audit 仓库写入权限

`nightly-scan.yml` 需要把公开生成物提交回 `quantskills/registry` 本仓库。

`nightly-audit.yml` 需要把详细报告提交回私有 `quantskills/registry-audit` 本仓库。

这一步使用 GitHub Actions 内置的 `GITHUB_TOKEN`,只在 registry 仓库生效。workflow 顶层权限保持:

```yaml
permissions:
  contents: write
```

不要把这个写权限扩展到 skill / agent 仓库。

## 工作流边界

默认工作流只做:

- 列出 `skill-*` / `agent-*` 仓库
- 克隆仓库
- 本地校验
- public registry 工作流生成公开 registry / INDEX / llms / marketplace
- private audit 工作流生成完整 reports
- 只 commit 当前仓库内的生成物

默认工作流不做:

- 不开 PR
- 不改 topics / description / homepage
- 不在 skill / agent 仓库开、关、编辑 issue
- 不触发其他仓库
- 不上传全组织镜像备份
- 不运行 AI 自动修复
- 不把 `health_items` / human-review 报告提交到 public registry

## 验证清单

配置完成后逐项验证:

- [ ] 用 `QS_READ_TOKEN` clone 一个 skill 或 agent 仓库应成功
- [ ] 用 `QS_READ_TOKEN` push 任意 skill 或 agent 仓库应失败
- [ ] 用 `QS_READ_TOKEN` 创建 PR 应失败
- [ ] 用 `QS_READ_TOKEN` 创建 issue 应失败
- [ ] 用 `QS_READ_TOKEN` 修改 topics / description / homepage 应失败
- [ ] 用 `QS_READ_TOKEN` 删除仓库或分支应失败
- [ ] 手动触发 public `nightly-scan --full` 应生成 `registry.json`
- [ ] public `registry.json` 不应包含 `health_items`
- [ ] public `registry` 不应包含 `reports/scan-*.json` 或 `reports/human-review-*.md`
- [ ] 手动触发 private `nightly-audit --full` 应生成 `reports/scan-YYYYMMDD.json`
- [ ] private audit 报告应包含完整 `health_items`

## 可选加固

建议在组织或仓库层面开启:

- Secret scanning
- Push protection
- 分支保护
- 禁止 force push
- 禁止删除默认分支

这些是平台级保护,独立于本审计流水线。
