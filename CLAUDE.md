# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

A single-file Flask web app that solves the Petrick's (Patrick) Method for minimal SOP (Sum of Products) Boolean simplification, supporting both single- and multiple-output problems. The UI and comments are in Traditional Chinese. The entire application — routes, solver logic, and the inline HTML template — lives in `patrick_method_solver.py`.

## Commands

```bash
pip install -r requirements.txt   # Flask 3.1 and its dependencies
python patrick_method_solver.py   # runs on 0.0.0.0, port from $PORT (default 5000)
```

There are no tests, linters, or build steps in this repository. The app is deployed to Render, which supplies the `PORT` environment variable — keep the `0.0.0.0` host binding intact.

Note: `requirements.txt` is UTF-16 encoded (saved on Windows). `pip` handles it, but naive text tools may show garbled content; preserve or normalize the encoding deliberately if you edit it.

## Verification workflow (驗收流程)

`REQUIREMENTS.md` is the single source of truth for acceptance criteria. These rules are mandatory:

- Any task that modifies code MUST run the `/verify` acceptance loop (defined in `.claude/commands/verify.md`) before being declared complete — even if the user didn't ask for verification. The loop: start the app, test every item in `REQUIREMENTS.md` with real requests, fix failures, regression-retest, repeat until all pass.
- The final report MUST include the full per-item result table. Any ❌ means the task is NOT complete; if an item still fails after 3 fix rounds, stop and report the blocker honestly instead of claiming success.
- If a new task introduces new requirements, add them to `REQUIREMENTS.md` first, then implement.
- Testing gotchas: use `curl --form-string` (not `-F`) for inputs containing `;`, and match `&#39;` for apostrophes in HTML responses. The built-in default example's F0 is mathematically unsolvable — "找不到涵蓋所有 minterm 的組合" there is correct behavior, not a bug.

## Architecture

Everything is in `patrick_method_solver.py`:

- **Web layer**: one route (`/`, GET+POST) rendering `HTML_PAGE` via `render_template_string`. Input arrives either from two form textareas or an uploaded `.txt` file (line 1 = prime implicants, line 2 = minterms).
- **Input format**: multiple outputs are separated by `;`, terms/minterms within one output by `,`. Example: PIs `A'B, AB; A'C` with minterms `1,3; 2,6` describes two functions F0 and F1. `parse_input` zips the PI groups with the minterm groups positionally.
- **Solver pipeline** for each output: `build_prime_chart` (maps each minterm to the PIs covering it) → `find_min_sop` (brute-force search over PI combinations of increasing size, returning the first combination that covers all minterms — guaranteeing minimal cardinality).
- **Boolean-term evaluation**: `get_covered_minterms` enumerates all assignments over a fixed variable order `A, B, C, D` (the app supports at most four variables) and tests each against the PI expression via `match_pi`/`split_literals`. Complemented literals are written with a trailing apostrophe (e.g. `A'B`), and a PI expression may itself contain `+`-separated parts.

Constraints baked into the code: 4 variables max, minterm indices derived from the binary assignment of `A..D` (A is the most significant bit), and minterms that aren't plain digits are silently dropped during parsing.
