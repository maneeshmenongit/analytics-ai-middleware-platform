---
name: test
description: Run tests for worldwise-agents — identify scope, write missing tests, fix failures.
argument-hint: "[module-or-file-path (e.g. agents/tools/doc_reader.py)]"
---

# Test Workflow

## Step 1: Identify Scope

**If the user passed an argument**, use that file/module as the target.

**If no argument**, find changed files:
```bash
git diff --name-only HEAD 2>/dev/null || echo "not a git repo"
```

If no git changes or not a git repo, ask: "Which module should I test? (e.g. `agents/tools/doc_reader.py`)"

## Step 2: Read the Code

Read the target source file(s). Also check `tests/` for existing test files matching the pattern `test_<module>.py`.

Summarize:
- What the module does
- What is already tested
- What is missing coverage (edge cases, error paths, schema validation)

## Step 3: Write Missing Tests

Use `pytest`. Test files go in `tests/` with pattern `test_<module>.py`.

Conventions for this project:
- Framework: **pytest**
- Test data: use inline fixtures or small temp files — do NOT point tests at real VoiceWise/HelmerWise paths
- For `doc_reader`: test with inline markdown strings written to `tmp_path`
- For `code_reader`: test with small synthetic `.py` fixture files, never the real VoiceWise repo
- For `reconciler` / `recommender`: mock the `anthropic` client — do not make real API calls in tests
- Assert on dataclass fields, not string output

Focus on:
- Happy path (valid input → correct output)
- Edge cases (empty input, malformed markdown, SyntaxError in `.py` files)
- Schema correctness (all required fields present, types match)
- Hard constraints (DocReader never raises, CodeReader never imports external code)

## Step 4: Run Tests

```bash
python -m pytest tests/ -v --tb=short 2>&1
```

## Step 5: Fix Failures

For each failure:
1. Determine if the bug is in the **test** (wrong expectation) or **source** (real bug)
2. Fix the right thing
3. Re-run until all tests pass

Do NOT suppress failures with `pytest.mark.skip` or broad `try/except` — fix them.

## Step 6: Report

```
## Test Results
- Target: <module(s)>
- Tests run: <N> | Passed: <N> | Failed: <N>
- New tests written: <N> (in <file>)
- Bugs found in source: <list or "none">
- Coverage gaps remaining: <list or "none">
```
