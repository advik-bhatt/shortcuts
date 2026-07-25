# shortcuts — agent rules

Global rules live in `advik-bhatt/knowledge-base` → CLAUDE.md (branch
discipline: all work commits directly to main, no worktrees, no feature
branches; commit author Advik Bhatt <advik.bhatt@gmail.com>; no model IDs
in commit messages).

## Merge desk (multi-thread pushes)

Parallel Claude threads share `main`. Never raw `git push`; push via
`sh .claude/merge-desk/sync-push.sh` (rebases, retries races, files a
conflict card on real collisions). On exit 42 follow the merge-desk skill
(`.claude/skills/merge-desk/`): resolve intent-first, then post the card
as a GitHub issue titled `[merge-desk] shortcuts: <plain summary>` so Advik can
approve, change, or revert. At session start, apply approved
`[merge-desk]` cards first and announce your goal on the
`[merge-desk] Thread board` issue.
