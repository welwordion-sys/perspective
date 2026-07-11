# Perspective — Session Bootstrap (BRIEFING.md)

**Updated:** 2026-07-08 · Two jobs: (1) introduce the project to a cold
session, (2) route to where live truth lives. Embedded design facts cite
their KB nodes; **on any conflict, the KB wins** — this file is a snapshot
and snapshots age.

## Project in one sentence
Representation Space Traversal AI — solves problems by traversing the space
of graph representations until one makes the answer obvious, rather than
computing the answer directly.

## Where truth lives
| What | Authority | Access |
|---|---|---|
| Live state, decisions, open questions | Supabase KB | `curl "https://oniywvgbjtusvrgoklrm.supabase.co/functions/v1/kb?q=node&project=meta&id=session_start"` — follow its instructions |
| Code | this repo, `main` | git / raw.githubusercontent |
| Reasoning discipline | ERS repo | `curl -sO https://raw.githubusercontent.com/welwordion-sys/ERS/main/reason_setter.py` (+ PROTOCOL.md); check version string line 1 (v0.4+), refetch if stale |

**With Supabase/MCP (verify per-session via tool check, never assume):** KB is
authoritative. **Without:** work from this file; anything live, ask Sven.

## How Perspective works (current as of 2026-07-08, per KB)

**Two systems.** Data Transformation System traverses representation space
via graph rewrite rules; Logic Rewriting System improves the rules by GA
(fitness: label-conditioned reproducibility).

**Substrate.** Directed graphs, two edge types (structural / operational),
no node attributes. Layer types: within-layer rules (same abstraction,
`3+4→7`) and layer transitions (change abstraction).

**Rules** are triples (pattern, graph2s, graph2o), fired in two passes:
match pattern → pass 1 rewrites structural (operational stripped) → pass 2
rewrites operational (structural stripped) → stripped edges reattach to
surviving nodes. Nodes absent from output are removed; unmatched output
nodes instantiate fresh. (operations.py, unchanged since 2026-05-06.)

**Number encoding — SPINE (KB: `Spine number encoding`, verified).** Spine
nodes chained structurally LSB→MSB; each spine node points operationally at
its own bit node; bit value = self-loop on the bit node; operator attaches
at the LSB spine node. Supersedes two earlier encodings (binary tree, flat
bit chain) — **chain-era rule traces do not carry over** (KB warning).

**Operators.** Identity by unique cycle size: `+`3 `-`4 `*`5 `/`6 `=`7
(sizes 1, 2 reserved for bit value / carry). Tail on the cycle = finished
(terminal); no tail = reducible. Known defect: the anchor does not
discriminate operand order — fix `operator_port_topology` (left→cycle[0],
right→cycle[1]) is designed, pending implementation (KB:
`operand_order_gap_root_cause`).

**Carry.** One STRUCTURAL edge into the result spine (KB:
`spine_carry_attaches_leaf_structural`, verified — supersedes the old
operational 2-cycle). The result-spine node is REQUIRED for carry
detection; a trim that drops it passes no-carry tests and breaks carry
(KB warning).

**Arithmetic pipeline — COMPLETE for addition.** `arithmetic_spine.py`
(register_all), `spine_bitadd_v2.py`, `spine_finalise_multibit.py`,
`prop_test.py`. 64/64 addition battery, 227/227 property tests. The old
23-rule arithmetic.py catalog is superseded. Subtraction: design validated
(KB: `subtraction_design`), implementation under active redesign — live in
the KB, not here.

**Grouping/dispatch** committed at `578e0f3`, selftest 36 rules PASS.
Soundness boundary: the transitivity bound holds for node-matching, NOT for
fusion — read KB `grouping_incremental_insert` before refactoring core_tree.

**Open design (documented, unimplemented):** compound match resolution —
overlapping rule firings merge rather than order (KB: `Compound Match
Resolution`).

## Working rules (stable)
- Truth over politeness; name errors directly; no unearned praise; flag
  tentative positions before stating them as conclusions.
- Pseudocode and changed-region diffs over full file dumps.
- Corrections edit the wrong claim in place — never append a contradicting
  note below it.
- Design decisions another session inherits: run the ERS setter first
  (enforcement criterion: KB `meta.workflow`).

## Session start without KB access
1. Say so, and that you're working from this file's snapshot.
2. Ask Sven for the live state of whatever you're touching.
3. Log every decision for KB push at session end.
