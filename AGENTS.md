# AGENTS.md - quantskills Registry 维护说明

你负责维护 quantskills Registry。默认先做只读核验；当用户明确授权某项发布、目录整理或修复时，可以在独立分支中修改本仓库、提交、push 并开 PR。

## 工作顺序

1. 读取当前分支、远端 head、工作树和生成脚本，确认修改范围。
2. 对签名 manifest、Registry head、snapshot digest 和 schema 做验证；验证失败时停止写入。
3. 修改唯一源文件或生成逻辑，再运行最小相关测试；不要手工编辑生成产物。
4. 生成并校验 `catalog.snapshot.json`、`registry.json`、README、INDEX、llms 和 marketplace 投影的一致性。
5. 检查 diff，提交到独立分支，使用普通 push，并在 PR 中记录测试、commit SHA、snapshot ID 和变更原因。
6. 只有 CI 通过且用户明确要求合并时才合并；完成标准是远端 commit、生成物哈希和验证结果均可复核。

## 维护边界

- 用户明确授权后可修改 Registry 源文件、生成脚本、测试和文档，可开修复 PR，也可 push 非强制更新的分支。
- 保持候选 skill/agent 仓库不变；目录下架使用可审计的 listing 状态，不删除仓库或历史记录。
- 公开目录只能由 Registry snapshot 派生，官网和导航不能手工维护名单。
- 对 warning / quarantined 项保留事实依据和人工复核标记，不擅自修改安全结论或评分。
- 不删除文件、分支、issue、PR 或仓库，不 force push，不改 git 历史、LICENSE、仓库可见性、topics、description、homepage 或 workflow，除非用户另行明确授权。
- 不读取、输出或持久化明文凭据，不尝试获取更高权限；网络操作只访问任务所需的公开或已授权接口。
- 不执行候选代码，不进行真实交易、外部写入、付费操作或候选网络访问。

## 输出纪律

报告应明确列出：修改文件、签名和 snapshot 绑定、测试命令及结果、远端分支和 commit SHA、PR 地址（如已创建）、官网/导航是否由同一 snapshot 派生，以及未执行的高风险动作。
