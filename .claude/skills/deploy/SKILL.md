---
name: deploy
description: Push worldwise-agents current branch to origin after verifying tests and safety checks pass.
argument-hint: ""
---

# Deploy — Push Current Branch

⚠️ Do NOT merge to `main`, create PRs, or modify any VoiceWise or HelmerWise files. Only push the current branch.

## Step 1: Check Branch State

```bash
git status
git branch --show-current
```

If there are uncommitted changes, ask the user: "There are uncommitted changes. Should I commit them first, or only push what's already committed?"

Do NOT proceed until the branch state is intentional.

## Step 2: Verify Safety Constraints

Before pushing, do a final check that no external repo files were touched:

```bash
git diff HEAD -- . ':(exclude).venv'
```

Scan the diff for any paths that reference VoiceWise or HelmerWise directories. If any are found, **stop** and report them as blockers.

## Step 3: Run Tests

```bash
python -m pytest tests/ -v --tb=short 2>&1
```

If tests fail, **stop**. Do not push. Report the failures.

## Step 4: Push

```bash
git push -u origin $(git branch --show-current)
```

⚠️ Do NOT force-push. Do NOT push to `main` directly.

If the push is rejected (upstream has diverged), report the conflict to the user and ask how to proceed — do not rebase or reset without explicit instruction.

## Step 5: Summary

```
## Push Summary
- Branch: <branch-name>
- Commits pushed: <N>
- Tests: all passing ✓
- Remote: origin/<branch> up to date
- External repos modified: none ✓
```
