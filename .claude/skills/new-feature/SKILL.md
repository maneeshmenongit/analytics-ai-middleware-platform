---
name: new-feature
description: Implement a new feature for worldwise-agents — read spec, plan, build, test, validate.
argument-hint: "[feature-name (e.g. doc-reader, code-reader, reconciler, recommender)]"
---

# New Feature Workflow

## Step 1: Understand the Project Structure

Read the following files to ground yourself before touching any code:
- `docs_to_claude/Base_architecture/Phase1/WORLDWISE_AGENTS_PHASE1_HANDOFF.md` — full architecture, module contracts, schemas, constraints
- `requirements.txt` — dependencies (anthropic, python-dotenv)
- `config/__init__.py`, `agents/__init__.py`, `core/__init__.py` — existing scaffolding

Do NOT proceed until you have read all files above.

**Hard constraints from the project (memorize these):**
- NEVER write to VoiceWise or HelmerWise repos — all file ops on those are read-only
- NEVER import VoiceWise code — use `ast.parse()` for static analysis only
- Full pipeline = at most 2 Claude calls (Reconciler + Recommender). DocReader and CodeReader are pure Python
- Feature IDs must be stable: `component_prefix + md5(feature_name)[:6]`

## Step 2: Identify the Feature

**If the user passed an argument** (e.g., `/new-feature doc-reader`), look up that module in the Phase 1 handoff doc.

**If no argument was provided**, ask: "Which feature should I implement? Options from Phase 1: doc-reader (1A), code-reader (1B), reconciler (1C), recommender (1D), refresh-script (1E)."

Summarize your understanding of the feature's:
- Input and output types (exact schemas from handoff doc)
- File it belongs to (`agents/tools/doc_reader.py`, etc.)
- Dependencies on other modules
- Any existing stubs or files already present

Wait for user confirmation before proceeding.

## Step 3: Plan

Enter plan mode. Present:
1. Files to create or modify (exact paths)
2. Classes and functions to implement (names and signatures)
3. How this connects to the rest of the pipeline
4. Test strategy (what to test, where tests go)
5. Any design decisions or ambiguities

Wait for user approval before writing any code.

## Step 4: Implement

Build the feature step by step per the handoff spec.

Follow these conventions:
- Use `dataclasses` for all schema types (DocFeatureSignal, CodeSignal, ReconciledFeature, Recommendation)
- Use `python-dotenv` via `config/settings.py` for env vars
- Never raise unhandled exceptions in reader tools — log warnings and continue
- Keep Claude calls minimal; pure-Python logic stays pure Python
- Tests go in `tests/` with pattern `test_<module>.py`

## Step 5: Run Tests

```bash
python -m pytest tests/ -v --tb=short 2>&1
```

If no test file exists yet, write one first (unit tests for the new module), then run.

Fix all failures before proceeding.

## Step 6: Validate End-to-End

If the feature is part of the pipeline (1A–1E), do a quick smoke test:

```bash
# For DocReader / CodeReader
python -c "from agents.tools.doc_reader import read_docs; print(read_docs('docs_to_claude')[:2])"

# For full pipeline (after 1E is implemented)
python scripts/refresh_tracker.py
```

Confirm no file in an external repo was modified.

## Step 7: Summary

Present:
```
## Feature Implemented: <name>
- File: <path>
- Functions/classes added: <list>
- Tests: <test file>, <N> tests passing
- Pipeline position: <1A/1B/1C/1D/1E>
- Hard constraints respected: read-only ✓ / no imports ✓ / Claude calls ≤2 ✓
```
