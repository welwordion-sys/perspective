# Rule grouping / grouped dispatch (optimization layer)

Status: PROTOTYPE, verified equivalent to baseline. NOT yet wired into the engine.
Behavior is unchanged because nothing calls this yet.

## What it is
An optimization over rule matching. It does NOT change what fires or how the
rewrite runs (operations.apply is untouched). It changes how the firing rule is
FOUND: instead of trying each rule's match in registry order, rules are clustered
into groups sharing a structural core; a group's core is matched once, then the
member is disambiguated by its delta.

## GA-safety: un-anchorable rules degrade, never crash
`group_core` raises `GroupCoreError` when a rule has no structurally unique
anchor node (malformed or fully-symmetric graph — possible from GA output).
`build_groups` catches this: the rule becomes its own singleton ground leaf
(matched directly via its existing view, identical to today's per-rule baseline)
and is recorded in the returned `degraded` list. It never merges, never crashes
the tree build. A spike in `degraded` is signal (generator producing rule shapes
the anchor logic can't seed), surfaced rather than swallowed.

NOTE: well-formed operator rules effectively never hit this — the directed op
tag + ordered operand edges guarantee a unique anchor even when operands are
equal ("symmetric" operands are not a symmetric graph). The guard is a net for
ill-formed GA output, not an expected path.

Signature: `build_groups(rule_names, c_min, f) -> (matchers, dendro, degraded)`.

## Population core-finder (pop_core.py) — EXPLORATORY prototype, not wired in
An alternative to anchor-growth `group_core`, motivated by BRIEFING-4 drift-1
(group_core grows from one anchor, not subgraph matching) and by the failure of
single-path methods on disconnected invariant structure — the carry-cycle island
{0,1}, which attaches to the main core only through a delta node and so is never
reached by connected growth from the op-tag anchor.

Mechanism (mirrors the system's own GA philosophy): grow a POPULATION of varied
random edge-walks, not one subgraph. The shared core is the UNION of edges matched
across the population, NOT the intersection of their prefixes (measured: union
recovers 60/60 core edges incl. the island; consensus/intersection recovers 0).
Uses NO node-id correspondence — walks match by edge content — so this is the path
that should generalize to GA graphs where intersection-by-id is unavailable.

Per-edge delta-tally feedback (soft bias toward high-match/low-stop edges, never
zero probability) cuts sequences-to-full-coverage 2.7–5x, most on the hardest
(most-delta) case. The ONLY strategy knob is `_choose_next` — the clean seam a
traveler strategy replaces, consuming the tally as a feature.

VALIDATED ONLY on shared-id carriers against an id-based ground truth. The id-free
generalization (the actual reason to prefer this over intersection-by-id) is
argued but UNMEASURED — no non-shared-id structurally-related pair exists yet.
Two regimes this clarifies: shared-id members (authored carriers, GA mutations of
one parent) → intersection-by-id is exact and trivial; independent-lineage members
(recombination, cross-lineage) → need this id-free structural method.

See test_pop_core.py (regression: union recovers full core incl. island; feedback
beats blind).

## Anchor + growth fixes (from BRIEFING-4 / KB grouping_anchor_picks_the_delta)The original `_pick_anchor` chose the highest-degree unique node, which on the
real bit_add carriers landed in the result-buffer region — exactly the
result-width delta — and raised a false `anchor feature mismatch`. Two fixes:

1. **Anchor (`_pick_group_anchor`)**: pick the op/cyc HUB (feature (1,0,2,1) on
   these carriers), resolving feature-twins by neighbour-signature rather than
   requiring per-member uniqueness. The multibit-result delta gives a second node
   the hub's feature, so a strict-uniqueness gate wrongly fell back to a
   degenerate leaf; resolve-by-signature picks the true hub anyway.
2. **Growth disambiguation**: when a BFS step offers >1 feature-equal candidate,
   keep only those whose edges to ALREADY-corresponded nodes match canon's
   (structural disambiguation, fail-closed). The old forced-unique growth bailed
   at the first ambiguity and stalled at 2/14 nodes.

Verified on the three DB-exact carriers (core_tt_2bit, core_mres_multibit,
core_mop_multibit): anchor resolves to node 7 in all three; shared core grows to
8/14 (was 2/14); delta is a consistent 6 nodes [0,1,6,8,13,19] (operand-spine +
result-buffer region — the width/carry-varying nodes). See test_carriers.py.

OPEN (carried from briefing): whether 8 is the COMPLETE shared core or whether a
few delta nodes are shared-but-unreached because their only correspondence path
runs through a genuinely-delta node. Disambiguating growth got 2→8; proving 8 is
maximal is not done.

## Edge-type normalization (mixed-source safety)
`_input_relations` returns EdgeType enums (registered rules); clean-table carrier
adapters use bare strings ('struct'/'op'). All etype `==` comparisons in growth,
disambiguation, and the shared-edge check would silently compare enum vs string
(always False -> zero candidates -> spurious GroupCoreError or empty core) the
moment a group mixed both sources. Fixed by canonicalizing every relation etype
to a string in `_profile` (`_canon_etype`), at the boundary, so all downstream
`==` compare like with like. Latent until sources are mixed (all runs so far were
single-source, which is why it never bit). Caught in review by the BRIEFING-4
session.

## Files
- grouping.py : group_core() — anchored shared-subgraph growth with forced-unique
  correspondence + strict identity check. Returns shared core + per-rule delta.
- dispatch.py : agglomerate() (bottom-up clustering, AND-gate c_min & f),
  GroupMatcher, build_groups(), and the equivalence harness
  (flat_baseline vs grouped_dispatch).
- verify.py   : drives real reductions, asserts grouped == flat at every state.
- selftest.py : one-shot PASS/FAIL; also asserts degraded==[] for clean input.
- test_degrade.py : fault-injection — forces GroupCoreError, proves the build
  degrades the rule to a singleton and records it instead of crashing.

## Settled design decisions
- Bottom-up agglomeration (not top-down split): top-down stalls because the
  discriminating positions (operand bits) are in the delta, not the core, so
  there is nothing to split on. Bottom-up never needs to name a split feature;
  pairwise core size carries it implicitly.
- AND-gate: a merge is valid iff shared_abs >= c_min AND min_ratio >= f.
  Percent floor cuts on density (scales with rule size); absolute floor is the
  "is the core worth materializing" backstop. AND fails toward tighter/more
  groups (safe direction: degrades to per-rule baseline, never corrupts).
- Anchor: deterministic, the unique-feature node (op node for arithmetic rules).
  Raises GroupCoreError if no structurally unique node exists (symmetric GA rule)
  — fails loudly rather than guessing a correspondence.

## Verified
- 8 registered bit_add variants -> 2 groups (c0 x4 core_abs=6/0.60, c1 x4 8/0.67).
  Carry boundary recovered automatically from pairwise core, no arithmetic prior.
- grouped_dispatch == flat_baseline across 96 states over 8 reductions (0 mismatch).

## NOT done (open)
- Speed win not yet realized: dispatch() still confirms via each member's full
  match (correctness-first). The core-match-once gate is designed but not wired
  into the dispatch path; both core match and per-member confirm currently run.
  Next: replace confirmation loop with position-keyed core gate, re-run verify.py.
- Core-stability-under-merge (cluster core not eroding as members join) holds for
  these arithmetic families; NOT proven general. Watch for GA rules.
- Agglomeration is O(clusters^2) core computations per round; fine at 8, needs
  caching/incremental recompute at the planned 213 variants.
- Insertion point: the engine's rule-iteration loop (the driver that calls
  operations.apply per rule). That driver is NOT in the staged file set; the
  one-line seam is: `for rule in registry: apply(g,rule)` -> `for group: m =
  group.dispatch(g); if m: apply(g, registry[m])`. apply() itself unchanged.

## Re-run the check
    PYTHONPATH=<repo with basic_machinery> python3 verify.py
    # expect: checks=96 mismatches=0 EQUIVALENT
