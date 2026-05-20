# Perspective — Mobile Session Briefing
**Updated:** 2026-05-10 | **Next task:** P2 — Write tests, validate apply() end-to-end

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
- `basic_machinery/graph.py` — PerspectiveGraph, directed graph with binary edge typing, node/edge management, copy, restore, subgraph(). Unchanged.
- `basic_machinery/operations.py` — Triple graph schema (pattern, graph2s, graph2o). Committed 2026-05-06.
- 9 tests — ALL BROKEN by operations.py redesign, need rewriting.

**P2 — In progress**
- `basic_machinery/encoding.py` — REWRITTEN this session (2026-05-10). See encoding decisions below.
- `basic_machinery/arithmetic.py` — REWRITTEN this session (2026-05-10). 23 rules, all triple schema. See rule set below.
- Tests: not yet written.

---

## operations.py schema (complete, committed 2026-05-06)

**Triple schema:** (pattern, graph2s, graph2o)
- `pattern` — mixed edge types, used for matching
- `graph2s` — strip OPERATIONAL, output STRUCTURAL. Pass 1.
- `graph2o` — strip STRUCTURAL, output OPERATIONAL. Pass 2.

**Firing sequence:**
1. match(pattern, graph) → node_map
2. Pass 1: strip operational → match graph2s input → follow mapping → write structural output → reattach operational via step 6
3. Pass 2: strip structural (updated_map from Pass 1) → match graph2o input → follow mapping → write operational output → reattach structural via step 6

**Key behaviours:**
- Nodes absent from transition output are removed (step 4b)
- New nodes in transition not matched from input are instantiated fresh
- Step 6 reattaches stripped edges to surviving mapped nodes — enables external edge rewiring without including parent in pattern
- restore() is a standalone function: snapshot → apply → revert on failure

---

## Encoding decisions (complete, encoding.py rewritten 2026-05-10)

**Tag design:**
- `_tag_cycle(node, size)` — unfinished operator/equality. Directed cycle of `size` nodes. cycle[0] gets a left anchor (dead-end structural node) for operand asymmetry and GA grammar consistency.
- `_tag_cycle_plus(node, size)` — finished operator/equality. Same as _tag_cycle but cycle[-1] also has a tail node. Tail = finished state.
- Both functions include the anchor — uniform grammar for GA mutation.

**Operator cycle sizes (unique per operator, no overloading):**
- `+`: 3-cycle
- `-`: 4-cycle
- `*`: 5-cycle
- `/`: 6-cycle
- `=`: 7-cycle
- Sizes 1 (bit value 1) and 2 (carry marker) reserved.

**Finished/unfinished semantics:**
- Unfinished = operator can still be reduced (both operands are concrete numbers). Arithmetic rules fire on unfinished operators.
- Finished = terminal, no rules fire. Happens when at least one operand contains a parameter.
- build_operator(graph, op, finished=False) — default unfinished.

**Numbers:** Open-length binary tree. MSB at root, LSB at deepest right leaf. Empty node = 0, self-loop = 1. build_number returns (root, lsb) tuple — lsb known at construction, no traversal needed.

**Parameters:** Bidirectional structural edge to companion node. build_parameter returns (root, lsb) tuple where both are the same node.

**connect_operands:** Now takes (op_node, left_root, left_lsb, right_root, right_lsb). Position edges attached to LSBs at encode time. Applies to all operators — bit traversal is universal.

**Negative numbers:** Represented as `0 - n` subtree.

**Carry marker:** 2-cycle. One node attached to result node via operational edge. Asymmetry from directionality of that operational edge — no extra structure needed.

**Position pointer:** Two operational edges from operator node to current bit position (LSB initially). Advance = position edge moves to parent. Parent included in pattern for match — node switching handles the rest.

**Tombstone marker:** Operational self-loop on node. Propagated to structural children by tombstone_gc rule.

**Seed rules (in encoding.py, triple schema):**
- add_zero_collapse: x + 0 -> x
- sub_zero_collapse: x - 0 -> x
- mul_one_collapse: x * 1 -> x
- div_one_collapse: x / 1 -> x
- mul_zero_collapse: x * 0 -> 0

---

## Arithmetic rule set (arithmetic.py, 23 rules, triple schema)

**add_init (4 rules):** add_init_00, add_init_01, add_init_10, add_init_11
- Pattern: op node + left LSB + right LSB + left parent + right parent. No result node.
- graph2s: create result node with correct bit tag.
- graph2o: wire op → left_parent, op → right_parent, op → result. Add carry if needed.

**bit_add (8 rules):** bit_add_XY_cZ for X,Y in {0,1}, Z in {0,1}
- Pattern: op node + left bit + parent + right bit + parent + result node. Carry encoded as 2-cycle on result node.
- graph2s: retag result node for new bit value. Carry 2-cycle absent from transition = removed.
- graph2o: advance position edges to parents. Rewire op → result. Add carry if produced.

**drain (8 rules):** drain_left/right_B_cC for B in {0,1}, C in {0,1}
- Fires when one side exhausted (no parent in pattern). Active side advances, exhausted side stays.
- 4 rules per side (bit × carry).

**add_finalise (8 rules):** add_finalise_LR_cC for L,R,C in {0,1}
- Fires when both positions at MSB (no parents). Op node recycled as result root — tag structure removed by step 4b, bare op node inherits parent's operational edge.
- graph2s: connect recycled op node to result tree. If carry_out: create extra MSB node (value=1) above result.
- graph2o: empty.

**tombstone_gc (1 rule):**
- Pattern: tombstoned node (operational self-loop) + structural child.
- graph2s: child gets tombstone. Parent removed.

---

## Design decisions made this session

1. Operator identity by unique cycle size — no overloading, no tail for identity.
2. Tail = finished state uniformly across all operators and equality.
3. Anchor off cycle[0] on all tags — operand asymmetry + GA grammar consistency.
4. build_number returns (root, lsb) — lsb known at construction.
5. connect_operands attaches to LSBs — universal, applies to all operators.
6. Carry marker on result node, not op node — op node pattern stays uniform across bit rules.
7. Tombstone = operational self-loop (not 3-node chain as in old design).
8. Op node recycled as result root in add_finalise — no rewiring problem.
9. Drain rules handle exhausted side by pattern absence of parent — no explicit exhaustion marker.
10. Layer transitions (not hypergraphs) will solve wildcard problem at higher abstraction level — not a P2 concern.

---

## Next session task

**Write tests.** This will immediately surface whether _apply_pass handles node mapping correctly for the new transition graphs. Start with:
1. add_init_00 end-to-end — simplest rule, validates the full apply() pipeline
2. bit_add_01_c0 — validates position advance and result tagging
3. add_finalise_00_c0 — validates op node recycling
4. One seed rule — validates survivor node reattachment via step 6

All 9 old tests are broken — rewrite against new schema after the above validate.

---

## Open questions
- Verify operand left/right order survives match() permutation — critical before subtraction rules
- Wildcard matching deferred to layer transition design
- Hyperedges deferred to P6
- match() is O(n!) — acceptable for prototype, flagged for P6 profiling

---

## Architecture essentials

**Two systems:**
- Data Transformation System — traverses representation space using reversible graph rules.
- Logic Rewriting System — improves rules using GA. Fitness: label-conditioned reproducibility.

**Substrate:** Directed graphs, binary edge types (structural / operational). No node attributes, no weights.

**Upgrade paths:** Hypergraphs, weighted graphs — named but deferred.

**Layer types:**
- Within-layer: same abstraction level (e.g. `3+4 → 7`)
- Layer transition: changes abstraction level

**Test sequence (planned):** Arithmetic equation solving → Symbol finding in pictures → further tests → meta-level scope increase.

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
>
> Session 2026-05-20 summary — add to P2 status:
Engine (operations.py) significantly reworked:

Step 1 now converts strip_type edges to output_type (not removes) to preserve structural context for matching
Step 2 identifies output-only nodes as has_incoming - has_outgoing strip_type edges
Step 3 builds input subgraph excluding output-only nodes, strips strip_type edges for matching
Seed loop seeds all non-output-only matched nodes

Arithmetic (arithmetic.py):

add_init pattern has no parents — correct
bit_add, drain, add_finalise patterns use _add_finished_op_node — correct
add_init g2s uses _add_finished_op_node + OPERATIONAL scaffold — partially working

13/33 tests passing. Open problems:

add_init g2s — op cycle nodes are deleted instead of surviving. Transition needs explicit input→output node pairs for all surviving nodes, not just OPERATIONAL scaffold. The cycle nodes have no OPERATIONAL edges mapping them to output counterparts.
bit_add/drain/add_finalise patterns fail — consequence of problem 1 (op has no cycle after add_init fires)
tombstone_gc — parent not removed, child not getting tombstone
Seed loop if t_input in has_outgoing may need if t_input not in output_only once problem 1 fixed — but that caused regressions this session

Next session priority: Fix add_init g2s with proper input→output node pairs for all surviving structure. Verify cycle survives. Then check bit_add/drain/finalise cascade.
