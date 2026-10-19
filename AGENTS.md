# AGENTS.md

## Agent skills

### Issue tracker

Issues, specs, and tickets live as GitHub issues. See `docs/agents/issue-tracker.md`.

**完成一张票 = 留下带证据的 resolution 评论 + 关票。** 阻塞边靠关票解锁 —— 票开着，下游永远排不上。

### Triage labels

Default five-role vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `GLOSSARY.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.

### Releasing

**提交 ≠ 发版。** 小 fix（注释/测试/文档/文案）只提交到 `main`，不动 `version`、不打 tag。
只有「用户照 README 用一遍能看出不一样」的变化才发 Release。见 `docs/agents/release-policy.md`。

### 工作树

并行任务用 `git worktree add .slim/worktrees/<name>`，**不要在共享工作树里和别的 lane 抢同一批文件**。

