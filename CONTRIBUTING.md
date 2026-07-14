# 贡献指南

感谢你帮助改进 Badminton Skills Coach。这个仓库优先接受可验证、范围清楚且不会引入版权或隐私风险的改动。

## 可以贡献什么

- 修复检索、队列、验证或更新脚本中的缺陷。
- 改进 Skill 回答规范、检索规则和回归测试。
- 报告视频分类错误、失效链接或知识库遗漏。
- 改进主题图谱、维护流程和跨平台兼容性。

## 提交前

1. 较大的功能改动请先创建 Issue，说明目标、范围和验证方法。
2. 从 `develop` 创建短期分支；稳定修复也应通过 Pull Request 合入 `main`。
3. 不要提交原始视频、音频、完整转写、临时媒体地址、私人聊天记录、联系方式或本地反馈队列。
4. 涉及刘辉教学内容时，请保留公开视频链接和可核对的来源信息，不要声称获得本人背书。

## 本地验证

至少运行与你改动相关的测试。提交完整流水线或共享逻辑改动时，运行：

```bash
python3 scripts/test_douyin_pipeline.py
python3 scripts/test_search_knowledge.py
python3 scripts/evaluate_answer_policy.py
python3 scripts/evaluate_retrieval.py
python3 scripts/validate_project.py
```

## Pull Request

请在 PR 中说明：

- 改了什么，以及为什么需要改。
- 影响了哪些 Skill、知识库或维护流程。
- 实际运行过哪些测试及其结果。
- 是否涉及第三方内容、隐私数据或生成产物。

维护者会优先检查行为回归、证据可追溯性、隐私边界和知识库同步状态。
