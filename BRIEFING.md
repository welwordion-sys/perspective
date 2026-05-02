# Perspective — Mobile Session Briefing
**Updated:** 2026-05-02 | **Next task:** P2 — Input Layer and Encoding

---

## Project in one sentence
Representation Space Traversal AI — a system that solves problems by traversing the space of graph representations until it finds one where the answer is obvious, rather than computing the answer directly.

---

## Stack
- Python 3.12, PyTorch 2.5.1, PyTorch Geometric 2.7.0, CUDA 12.1
- GPU: NVIDIA RTX 4060 Ti 16GB
- Repo: github.com/welwordion-sys/perspective
- Local: D:\Projects\perspective
- Activate env: `.venv\Scripts\activate` from D:\Projects\perspective

---

## What exists
**P1 — Complete (2026-05-01)**
- `basic_machinery/graph.py` — PerspectiveGraph, directed graph with binary edge typing (structural / operational), node/edge management, copy, restore
- `basic_machinery/operations.py` — Graph Operation Interface: match, apply, revert, complexity, lookup, register
- 9 passing tests

---

## Current phase: P2 — Input Layer and Encoding

**Goal:** Encode arithmetic expressions and linear equations as directed graphs.

**Encoding decisions:**
- Each constant (e.g. `3`, `4`, `10`) encoded as a binary tree rooted at its node — no node attributes, identity emerges from structure
- Operators (`+`, `-`, `*`, `/`) and equality (`=`) as internal nodes
- Variable `x` as anonymous structural node — no special status
- Input layer is immutable — no rules fire on it

**Label format:**
- Pure arithmetic (e.g. `3 + 4`): label is terminal value node — `7`. No wrapper.
- Equations (e.g. `2x + 4 = 10`): label is solved form graph — `x = 3`. Irreducible — `x = 3` does NOT collapse to `3`.
- Collapse rule: `x = x → x`, `3 = 3 → 3`, but `x = 3` stays as-is.

**Complexity ladder (train in this order):**
1. Pure arithmetic — `3 + 4`, label: `7`
2. One-step solving — `x + 4 = 7`, label: `x = 3`
3. Two-step solving — `2x + 4 = 10`, label: `x = 3`
4. Variable on both sides — `2x + 4 = 3x - 1`, label: `x = 5`

**Seed rules:**
- Bootstrap scaffold — present at GA generation zero, fully mutable
- Handle large base graph size before library accumulates
- Displacement by library-informed rules is the success signal
- If seed rules dominate after N generations, library accumulation is broken

**Exit condition:** Expressions reliably converted to base graphs. Sample manually inspected and encoding confirmed sane.

---

## Architecture essentials

**Two systems:**
- Data Transformation System — traverses representation space using reversible graph rules. Owns the library.
- Logic Rewriting System — improves the rules using a GA. Fitness signal: label-conditioned reproducibility (minimize variance in subgraph output per label across expressions).

**Library:** Entries are byproducts of GA convergence — subgraphs that consistently appear under converged rules for a given label earn entry. Not frequency, not MDL.

**Reversibility:** Every rule firing is reversible. Rule path is the inverse map. The pair (result graph + rule path) is the full reversible state.

**Substrate:** Directed graphs, binary edge types only (structural / operational). No node attributes, no weights, no hyperedges in base prototype.

**P6 gate (future):** Binary decision — directed graph sufficient (pass) or hyperedges needed (fail). Fail is additive — directed graph is hypergraph at k=2, everything recycles.

---

## Open critical questions
- q_07: Are hyperedges required? (answered at P6)
- q_03: Invariant retention mechanism — how does system decide what to keep without explicit confirmation?

---

## Communication rules (applies to this session)
- No softening — name errors directly
- Default: user is competent
- No praise unless genuinely non-obvious
- Useful over agreeable
- Flag tentative positions explicitly before stating them as conclusions
- This is bidirectional — Claude flags user reasoning gaps too

---

## Mobile workflow
- No KB writes on mobile — note decisions as a list, push from PC
- No code implementation on mobile — describe intent, implement on PC
- Architecture and design discussion: fine on mobile
- End of session: list any decisions made for PC push

---

## Next session start prompt
Paste this file and add:
> "No GitHub access. Mobile session. Current task: P2 input encoding. [your question or task]"
