# quantskills.ai 对接说明(交给网站维护方)

GitHub 组织侧每晚自动产出并维护以下公开数据,网站侧按需消费即可,**双方互不需要对方任何权限**。

## 数据接口

| 内容 | 稳定 URL | 用途 |
| --- | --- | --- |
| 注册表(机器读) | `https://raw.githubusercontent.com/quantskills/registry/main/registry.json` | 网站全部 skill / agent 卡片、标签、分类、搜索的唯一数据源 |
| 注册表结构定义 | `https://raw.githubusercontent.com/quantskills/registry/main/schema/registry.schema.json` | 字段语义见此 schema |
| agent 索引 | `https://raw.githubusercontent.com/quantskills/registry/main/llms.txt` | 建议原样部署到网站根目录 `https://quantskills.ai/llms.txt` |

## 字段语义要点

- `project_type`:`skill` / `agent`,建议作为一级展示分区。
- `declaration_file`:`SKILL.md` / `AGENTS.md`,说明该资产的声明入口。
- public registry 不包含 `health_items` 和人工复核细节。
- `quarantined` 项目不会进入 public registry;详细原因只保存在维护者本地审计输出中。
- `validation_level`:`listed` / `runnable` / `verified`,对应组织公开的三级验证体系,建议作为卡片徽章。
- `summary_zh` / `summary_en`:卡片一句话简介(双语)。
- `commit_sha` + `last_validated`:该条目对应的已验证版本与日期。

## 更新节奏与消费方式

- 注册表每晚(北京时间约 00:30-01:00)自动更新一次;条目对应仓库无变更时内容不变。
- 推荐**拉取模式**:静态站在每次构建时拉取上述 URL;或设置每日定时重建。
- 如需**推送模式**(注册表一更新立即重建):请向组织侧提供你们的 build hook URL(Vercel/Netlify/CF Pages 均支持),组织侧会在流水线末尾加一步通知。

## 约定

- 网站不应自行维护任何 skill / agent 清单、标签、描述的副本数据——一切以 registry.json 为准,避免两边漂移。
- registry.json 的字段只增不改不删(向后兼容);如需破坏性变更会提前在 registry 仓库 issue 公告。
