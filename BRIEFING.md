# Perspective — Session Bootstrap (BRIEFING.md)

**Updated:** 2026-07-08 · **Design rule for this file:** only *frozen* facts
(completed milestones) are embedded here; everything *live* is a pointer.
Live state duplicated into this file rots — the previous revision proved it.

## Project in one sentence
Representation Space Traversal AI — solves problems by traversing the space
of graph representations until one makes the answer obvious, rather than
computing the answer directly.

## Where truth lives (authority map)
| What | Authority | Access |
|---|---|---|
| Live project state, open questions, decisions | Supabase KB | `curl "https://oniywvgbjtusvrgoklrm.supabase.co/functions/v1/kb?q=node&project=meta&id=session_start"` — follow its instructions |
| Code | this repo, `main` | git / raw.githubusercontent |
| Reasoning discipline | ERS repo | `curl -sO https://raw.githubusercontent.com/welwordion-sys/ERS/main/reason_setter.py` (+ `PROTOCOL.md`); verify version string in line 1 (v0.4+), refetch if stale |

**With Supabase/MCP access (verify per-session, never assume):** the KB is
authoritative; ignore anything here that conflicts. **Without it:** work from
the frozen facts below; anything live, ask Sven.

## Frozen facts (completed, safe to rely on)
- **Stack:** Python 3.12, PyTorch 2.5.1 + PyG 2.7.0, CUDA 12.1, RTX 4060 Ti 16GB.
  Local: `D:\Projects\perspective`, `.venv\Scripts\activate`.
- **Substrate:** directed graphs, binary edge types (structural/operational),
  no node attributes. Rules are (pattern, graph2s, graph2o) triples; two-pass
  firing with strip/reattach (operations.py, committed 2026-05-06).
- **Addition pipeline: COMPLETE.** Spine-encoded, full 64-case battery passing.
  Files: `spine_bitadd_v2.py`, `spine_finalise_multibit.py`, `prop_test.py`,
  `arithmetic_spine.py`.
- **Grouping/dispatch: committed** at `578e0f3` — incremental core-tree insert
  with fingerprint gating; end-to-end selftest 36 rules PASS. Soundness
  boundary recorded in KB node `grouping_incremental_insert` (transitivity
  bound is sound for node-matching, NOT for fusion — read before refactoring).
- **Subtraction:** design validated (KB `subtraction_design`), implementation
  under active redesign — state lives in the KB, not here.
- **Known open design:** compound match resolution (overlapping rule firings
  merge rather than order) is documented in the KB but unimplemented.

## Working rules (stable)
- Truth over politeness; name errors directly; no unearned praise; flag
  tentative positions before stating them as conclusions.
- Pseudocode and changed-region diffs over full file dumps.
- Corrections edit the wrong claim in place — never append a contradicting
  note below it (this file's previous revision died of that).
- Mobile ≠ no writes: MCP/Supabase capability is verified per session via
  tool check, never inferred from device. Without write capability: note
  decisions for Sven to push, implement nothing blind.
- Design decisions another session will inherit: run the ERS setter first
  (see ERS repo PROTOCOL.md; enforcement criterion in KB `meta.workflow`).

## Session start without KB access — do this
1. State that you have no KB access and are working from BRIEFING.md frozen facts.
2. Ask Sven for the live state of whatever you're about to touch.
3. Log every decision for PC/KB push at session end.
