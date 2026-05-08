# Perspective — Mobile Session Briefing
**Updated:** 2026-05-06 | **Next task:** P2 — Rewrite seed rules and arithmetic rules as triple graph schema

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
- `basic_machinery/graph.py` — PerspectiveGraph, directed graph with binary edge typing, node/edge management, copy, restore, subgraph()
- `basic_machinery/operations.py` — REDESIGNED this session (see below)
- 9 tests — ALL BROKEN by operations.py redesign, need rewriting

**P2 — In progress**
- `basic_machinery/encoding.py` — live, smoke tested 2026-05-04
- Arithmetic rule design: complete (this session)
- Rule implementation: not started

---

## operations.py redesign (this session)

**Old schema:** OperationDefinition(name, pattern, rewrite: Callable)

**New schema:** OperationDefinition(name, pattern, graph2s, graph2o)

Rules are now pure graph structures — no imperative rewrite functions.

**Triple schema:** (pattern, graph2s, graph2o)
- `pattern` — mixed edge types, used for matching
- `graph2s` — two structural subgraphs (input side + output side) linked by operational edges as mapping. Pass 1 fires this: strips operational edges, matches input subgraph, follows operational mapping edges, writes new structural edges.
- `graph2o` — two operational subgraphs linked by structural edges as mapping. Pass 2 fires this: strips structural edges, matches input subgraph, follows structural mapping edges, writes new operational edges.

**Firing sequence:**
1. match(pattern, graph) → node_map
2. Pass 1: strip operational → apply graph2s → reattach operational
3. Pass 2: strip structural (using updated_map from Pass 1) → apply graph2o → reattach structural

**Deletion:** nodes not in output_node_map are removed from graph. Tombstone GC handles operand tree cleanup.
**Merge:** multiple mapping edges to same output node — first mapping wins.
**New nodes:** transition output nodes not mapped from any input node → instantiated as fresh graph nodes.
**Pass 1→2 handoff:** updated_map passed to Pass 2. Deleted nodes silently ignored in Pass 2 (stable under mutation).

**restore()** is now a standalone function in operations.py: snapshot → apply → revert on failure.

---

## Encoding decisions (complete)

**Numbers:** Open-length binary tree. MSB at root, LSB at deepest right leaf. Empty node = 0, self-loop = 1.

**Operators:** Cycle-based structural tags. +: 3-cycle. -: 3-cycle + tail. *: 4-cycle. /: 4-cycle + tail. Operands via operational edges.

**Equality:** Unfinished = 5-cycle tag. Finished = 5-cycle + tail.

**Parameters:** Bidirectional structural edge to companion node.

**Negative numbers:** Represented as `0 - n` subtree. No sign node. sub_zero_collapse fires on right-operand-zero only — no conflict.

**Carry marker:** 2-cycle attached to operator node via structural edge. Distinct shape required — parameter shape rejected because rule mutation at meta-level could cause false matches across rule graphs.

**Tombstone marker:** 3-node chain (node → a → b, no cycles). Attached to operand root after finalisation. GC rule fires repeatedly until subtree consumed.

**Position pointer:** Two operational edges from operator node to current bit position in each operand tree. Start at LSB (deepest right leaf), advance toward root in lockstep.

---

## Arithmetic rule set (designed, not yet implemented as graph structures)

1. `add_init` — attaches two position edges to LSB of each operand tree
2. `bit_add_00_c0/c1`, `bit_add_01_c0/c1`, `bit_add_10_c0/c1`, `bit_add_11_c0/c1` — 8 bit rules
3. `drain_remaining` — handles unequal operand lengths with implicit zero
4. `add_finalise` — rewires parent to result, tombstones operand roots, removes operator node
5. `tombstone_gc` — fires on tombstone pattern, propagates tombstone to children, removes node

---

## Next session task

Rewrite all rules as triple graph schema (pattern, graph2s, graph2o). Start with `add_init` and one bit rule to validate apply() end-to-end before writing the full set. Also rewrite broken seed rules (neutral element collapses, zero product collapse).

**Open questions before writing rules:**
- Verify operand left/right order survives match() permutation — critical before subtraction rules
- Decide where rule graph construction helpers live: encoding.py, arithmetic.py, or rules/builders.py

---

## Architecture essentials

**Two systems:**
- Data Transformation System — traverses representation space using reversible graph rules. Owns the library.
- Logic Rewriting System — improves rules using GA. Fitness: label-conditioned reproducibility.

**Rule schema:** Triple (pattern, graph2s, graph2o). GA operates on each graph independently.

**Substrate:** Directed graphs, binary edge types (structural / operational). No node attributes, no weights, no hyperedges in base prototype.

**Layer types:**
- Within-layer: switches representation without changing abstraction level (e.g. `3+4 → 7`)
- Layer transition: changes abstraction level — collapses local detail into higher-level structure

---

## Open critical questions
- q_07: Are hyperedges required? (answered at P6)
- q_03: Invariant retention mechanism

---

## Communication rules
- No softening — name errors directly
- Default: user is competent
- No praise unless genuinely non-obvious
- Useful over agreeable
- Flag tentative positions before stating as conclusions

---

## Mobile workflow
- No KB writes on mobile — note decisions, push from PC
- No code implementation on mobile — describe intent, implement on PC
- End of session: list decisions for PC push

---

## Next session start prompt
Paste this file and add:
> "No GitHub access. Mobile session. [your question or task]"
