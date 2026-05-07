---
name: pre-deploy
description: Pre-deployment checklist for worldwise-agents — env vars, dependencies, tests, safety constraints.
argument-hint: ""
---

# Pre-Deployment Checklist

## Step 1: Identify What Changed

```bash
git log main..HEAD --oneline 2>/dev/null || git log --oneline -10
git diff main..HEAD --name-only 2>/dev/null || git status --short
```

Summarize the changes at a high level.

## Step 2: Check Environment Variables

Read `.env.example` and `config/settings.py`. Compare against any new code added.

List any env vars that are:
- New (added in this change, not yet in `.env.example`)
- Required but potentially unset
- Changed in meaning or format

Required vars for this project:
- `ANTHROPIC_API_KEY` — Anthropic API access
- `VOICEWISE_DOCS_PATH` — absolute path to VoiceWise docs directory (read-only)
- `VOICEWISE_REPO_PATH` — absolute path to VoiceWise repo root (read-only)

## Step 3: Check Dependencies

Check if `requirements.txt` changed:
```bash
git diff main..HEAD -- requirements.txt 2>/dev/null
```

If changed, note which packages were added/removed and whether they need to be installed.

## Step 4: Verify Safety Constraints

This project has hard read-only constraints. Verify the changed code obeys them.

For each modified file in `agents/` or `scripts/`, check:
- [ ] No `open(..., 'w')` calls against VoiceWise or HelmerWise paths
- [ ] No `os.remove()`, `shutil.*`, or `subprocess` calls that modify external state
- [ ] No `import` of VoiceWise or HelmerWise modules (only `ast.parse()` for static analysis)
- [ ] Claude API calls: Reconciler ≤ 1 call, Recommender ≤ 1 call, readers = 0

Report violations as blockers.

## Step 5: Run Tests

```bash
python -m pytest tests/ -v --tb=short 2>&1
```

If tests fail, **stop**. Do not proceed. Report failures clearly.

## Step 6: Smoke Test the Pipeline (if scripts changed)

If `scripts/refresh_tracker.py` or any agent module was modified:
```bash
python -c "
import sys
# Quick import check — verifies no syntax errors in core modules
from agents.tools import doc_reader, code_reader
from agents import reconciler, recommender
print('All imports OK')
" 2>&1
```

## Step 7: Output Checklist

```
### Env vars to set / verify:
- [ ] ANTHROPIC_API_KEY — required for Reconciler and Recommender Claude calls
- [ ] VOICEWISE_DOCS_PATH — required for DocReader
- [ ] VOICEWISE_REPO_PATH — required for CodeReader
[any new vars found in Step 2]

### Dependencies:
- [ ] pip install -r requirements.txt  (if requirements.txt changed)

### Safety constraints:
- [ ] No writes to external repos ✓/✗
- [ ] No VoiceWise imports ✓/✗
- [ ] Claude call budget respected ✓/✗

### Tests: passing ✓ / failing ✗
### Ready to deploy: YES / NO
```

If "Ready to deploy: NO", list the blockers clearly.
