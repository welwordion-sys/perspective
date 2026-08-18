"""
run_reduction.py — Stage 1a, first target problem: plain reduction.

Sven chose reduction over `x + 3 = 8`, which hangs on unfinished subtraction.
The criterion is therefore NOT "variable isolated" but "computed": the graph
sits on the result state.

ON TRUTH: there is no decode() in the substrate, so truth is checked
STRUCTURALLY. layer_battery.oracle_run() puts the same input through the flat
apply() and graph_equiv() compares the two. The criterion is handed an oracle
comparison, not a numeric one.

WHY THAT MATTERS BEYOND THIS FILE (§1, and Sven this session): Perspective is
not made for arithmetic — the arithmetic test was made for Perspective. So the
decoder, the oracle and this whole file are a FITNESS CRITERION slotted in at
the end. Everything domain-specific lives here, behind Criterion.holds(). The
GA never sees it. If something arithmetic leaks into ga.py, that is a bug in
ga.py, not a feature of the test.

KNOWN LIMIT OF THIS TEST, measured, not assumed: below ~64 rules every group
scores exactly 0 (8 samples per size: 4->0/8 fire, 64->1/8 nonzero, 257->8/8).
The search therefore has no gradient to climb from a cold start. That is a
property of the TEST — the 257 rules are a finished reducer in which nearly
every rule is needed for some input — not a defect of the GA. §1 predicts it:
arithmetic proves solving ability, not cleverness. Do not "fix" the GA against
it.

SECOND KNOWN LIMIT: addition has no sideways moves (reversibility 6/6 False in
the reference run), so §7 rewind cannot be exercised here at all, however well
it is built.
"""
from __future__ import annotations
import os, sys, time

_R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in ['', 'ga', 'grouping', 'builders', 'basic_machinery']:
    _q = os.path.join(_R, _p)
    if _q not in sys.path:
        sys.path.insert(0, _q)

import layer_battery as LB               # registers the 257 rules exactly once
from basic_machinery.graph import PerspectiveGraph
from basic_machinery.encoding import encode
from basic_machinery.operations import _registry
from ga import (GA, MoveWorks, KnownPattern, Run, commit_reversibility,
                   sideways_slots, rewind_and_measure, NotInBabyPhase)


def population(pairs):
    """The INPUT POPULATION (§3). Several inputs, not one — constitutive, not
    cosmetic: a travelpath is an algorithm, so every layer of it has to be
    tested against multiple inputs, or what is being tested is not the path."""
    inputs, oracles = [], []
    for a, b in pairs:
        expr = f"{a}+{b}={a+b}"
        g = PerspectiveGraph(); encode(g, expr)
        o = PerspectiveGraph(); encode(o, expr)
        inputs.append(g)
        oracles.append(LB.oracle_run(o))
    return inputs, oracles


def build_criterion(oracles):
    """The pattern: "this state is the computed one". Known, not statistically
    identified (§4: for arithmetic it is known). The statistical variant is the
    one that would make domain-indifference a second data point rather than a
    claim; it is not built yet.
    """
    def pattern(g: PerspectiveGraph) -> bool:
        # graph_equiv is the repo's own notion of truth (edge multiset over
        # node fingerprints). Empty error list means equal.
        return any(o is not None and not LB.graph_equiv(o, g) for o in oracles)

    return KnownPattern("computed", pattern)


def main():
    pairs = [(0, 1), (1, 1), (1, 2), (2, 1), (2, 3), (3, 3)]
    inputs, oracles = population(pairs)
    criterion = build_criterion(oracles)
    supply = list(_registry)

    print(f"Population: {len(inputs)} inputs {pairs}")
    print(f"Rule supply: {len(supply)}")

    # Sanity check: the START state must NOT satisfy the criterion. If it does,
    # the fitness measures nothing — §4 requires the pattern to be ABSENT where
    # it does not belong, and a pattern present everywhere separates nothing.
    start = criterion.evaluate(inputs, inputs)
    print(f"Start state against itself: {start}  "
          f"(must be ~0, else the criterion measures nothing)")

    # Reference: the full rule set as ONE part. This is the path that already
    # exists — the ceiling the search is measured against, not a result.
    moveworks = MoveWorks()
    t0 = time.time()
    ref = Run(inputs, criterion, moveworks, LB.seed_layer)
    path_ref, runs_ref = ref.walk([tuple(sorted(supply))])
    part = path_ref.parts[0] if path_ref.parts else None
    print(f"\nReference (full rule set, 1 part): quality "
          f"{path_ref.quality(None):+.2f}, depth {path_ref.depth}, "
          f"loop {part.is_loop if part else '-'}, "
          f"turns {part.turns if part else {}}  [{time.time()-t0:.1f}s]")

    # §6: reversibility is a property of the RULE GROUP over the POPULATION,
    # never of a single firing. Collected during the walk, committed only here.
    flags = commit_reversibility(ref.ledger, runs_ref, len(inputs))
    for group, value in flags.items():
        print(f"  group reversible: {value} — "
              f"{ref.ledger.reason(group, len(inputs))}")
        print(f"  verdict per input: {ref.ledger.verdicts[group]}")

    # §7: rewind is attempted for real, not merely located. On addition this is
    # expected to find nothing, because no group is reversible.
    rewinds = rewind_and_measure(ref, path_ref, flags, runs_ref, criterion)
    print(f"  §7 rewind slots evaluated: {rewinds or 'none (no sideways moves)'}")

    # The search.
    print("\n=== Search ===")
    t0 = time.time()
    ga = GA(inputs, criterion, supply, LB.seed_layer, moveworks, c=4.0, seed=1)
    out = ga.search(generations=4, width=3)
    print(f"Best quality {out.quality:+.2f} at depth {out.path.depth} "
          f"({len(out.plan)} parts)  [{time.time()-t0:.1f}s]")
    for i, (p, s) in enumerate(zip(out.path.parts, out.path.signals)):
        print(f"  part {i}: {len(p.group):>3} rules, loop={p.is_loop}, "
              f"turns {sorted(set(p.turns.values()))} | {s}")
    print(f"Credit per slot: {dict(out.attention.credit)}")
    print(f"Sideways slots (§7 candidates): {sideways_slots(out.path, out.flags)}")

    # §8/§9: the actions that would need mapping synthesis say so out loud
    # rather than pretending. This is deliberate scope, not an omission.
    try:
        ga.actions.recombine(supply[0], supply[1])
    except NotInBabyPhase as e:
        print(f"\nRecombination: deliberately not built — {e}")


if __name__ == '__main__':
    main()
