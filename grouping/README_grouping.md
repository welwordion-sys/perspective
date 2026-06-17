# Rule grouping / grouped dispatch (optimization layer)

Status: PROTOTYPE, verified equivalent to baseline. NOT yet wired into the engine.
Behavior is unchanged because nothing calls this yet.

## What it is
An optimization over rule matching. It does NOT change what fires or how the
rewrite runs (operations.apply is untouched). It changes how the firing rule is
FOUND: instead of trying each rule's match in registry order, rules are clustered
into groups sharing a structural core; a group's core is matched once, then the
member is disambiguated by its delta.

## Files
- grouping.py : group_core() — anchored shared-subgraph growth with forced-unique
  correspondence + strict identity check. Returns shared core + per-rule delta.
- dispatch.py : agglomerate() (bottom-up clustering, AND-gate c_min & f),
  GroupMatcher, build_groups(), and the equivalence harness
  (flat_baseline vs grouped_dispatch).
- verify.py   : drives real reductions, asserts grouped == flat at every state.

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
