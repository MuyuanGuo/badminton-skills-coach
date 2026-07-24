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

回答质量问题按以下顺序处理：

1. 在单题黄金集固定目标动作、直接证据、硬负例和答案边界。
2. 在问题理解集固定主体、条件、症状、否定和目标动作。
3. 在关系评测中加入自然改写及最接近的负例，验证共享核心证据与不得共享的范围。
4. 真实用户反馈必须加入 `critical_answer_snapshots.json` 并保存审核后的最终答案快照。
5. 修改后先跑受影响的确定性门禁，再用未泄露预期答案的新任务做盲测；保存原始回答、逐项审核结果和运行时指纹，合并前运行完整流水线。

新失败类型没有现成门禁时，先扩展评测方法，再修改运行时规则。不要用上层模型偶然答对来掩盖错误的底层意图或证据上下文。

`main` 与 `develop` 的最终回答质量必须通过 `scripts/paired_blind_evaluation.py` 做成对盲评，不能用确定性中间指标代替。冻结问题位于 `data/evaluation/paired_blind_holdout.json`，不得复制到规则 gold 或用于调参。两份答案运行记录必须覆盖同一 holdout、使用相同模型与生成参数，并分别记录 commit SHA。`prepare` 会随机化 A/B、单独输出映射密钥和人工评审模板；评审者在不知道分支身份时按真实问题理解、事实正确性、来源蕴含、重要遗漏、无依据结论和清晰度打分，之后才可用 `score` 解盲。映射密钥和未脱敏评审记录不要提交到仓库。

```bash
python3 scripts/paired_blind_evaluation.py prepare \
  --main-answers /private/path/main-answers.json \
  --develop-answers /private/path/develop-answers.json \
  --seed "private-random-seed" \
  --pairs /private/path/blinded-pairs.json \
  --key /private/path/branch-key.json \
  --review-template /private/path/reviews.json

python3 scripts/paired_blind_evaluation.py score \
  --pairs /private/path/blinded-pairs.json \
  --key /private/path/branch-key.json \
  --reviews /private/path/reviews.json
```

至少运行与你改动相关的测试。提交完整流水线或共享逻辑改动时，运行：

```bash
python3 scripts/test_douyin_pipeline.py
python3 scripts/test_search_knowledge.py
python3 scripts/evaluate_answer_policy.py
python3 scripts/evaluate_query_equivalence.py
python3 scripts/evaluate_answer_quality.py \
  --answers data/evaluation/answer_quality_answers.json \
  --min-approved 57 \
  --min-answer-snapshots 57 \
  --min-answer-snapshot-coverage 1.0 \
  --require-complete-answer-coverage \
  --require-critical-answer-coverage \
  --require-manual-review
python3 scripts/evaluate_forward_test_results.py
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
