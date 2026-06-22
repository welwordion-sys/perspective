"""
Population build-sequence core-finder (PROTOTYPE — exploratory, not wired in).

An alternative to anchor-growth group_core, motivated by BRIEFING-4 drift-1
(group_core does correspondence growth from one anchor, not subgraph matching) and
by the failure of single-path methods on disconnected invariant structure (the
carry-cycle island {0,1}, which connects to the core only through a delta node).

IDEA (population search, mirroring the system's own GA philosophy):
  - Don't grow ONE subgraph from an anchor. Grow a POPULATION of varied edge-walks.
  - Each walk = a random connected ordering of edges (can seed a new component, so
    it reaches islands). "Agreement" against another member = the consecutive-from-
    start run of edges also present there.
  - The shared core is the UNION of matched edges across the population — NOT the
    intersection of their prefixes. No single walk covers the core; the population
    collectively does. (Measured: union recovers 60/60 core edges; consensus/
    intersection recovers 0 — consensus is the wrong reading.)
  - MATCHING IS BY EDGE-TUPLE EQUALITY, WHICH INCLUDES NODE IDS. The agreement
    check `e in other_set` compares (src,tgt,kind,type) tuples, so two graphs match
    only where they share node IDs. TESTED (test_idfree.py): a graph vs its own
    relabeling recovers 0 edges. So this is NOT id-free, despite the population
    walk strategy itself being id-agnostic — the id-dependence lives in the
    matching step, not the walk.
  - CONSEQUENCE: pop_core works ONLY for shared-id members (authored carriers, GA
    mutations of one parent that preserve ids), where it duplicates the trivial
    intersection-by-id more expensively. On the id-free case it was meant for
    (recombination / cross-lineage GA output), it does NOTHING as written. Making
    it id-free requires matching edges by structural ROLE, which is the
    unsolved node-correspondence problem (anchors/islands/placeholder semantics) —
    the population walk relocated that problem into `e in other_set`, it did not
    solve it.
  - The one genuine contribution is the FEEDBACK-TALLY search efficiency below
    (3–5x fewer sequences), independent of the id issue.

FEEDBACK (per-edge delta tally, soft bias):
  - After each walk, matched edges get +match; the stopping edge gets +stop.
  - Next-edge choice is soft-weighted toward high-match / low-stop edges. SOFT, not
    hard: every connected edge keeps nonzero probability, preserving discovery and
    the union-coverage property.
  - Measured speedup (sequences-to-full-coverage, mean over 5 seeds):
        tt   8.0 -> 3.0  (2.7x)
        mres 66.4 -> 16.0 (4.2x)   <- biggest win on the hardest (most-delta) case
        mop  24.4 -> 6.4  (3.8x)
    Gain scales with difficulty: the more delta edges, the more the tally helps.

TRAVELER SEAM: the ONLY strategy knob is the next-edge choice (`_choose_next`).
Blind = uniform random; feedback = tally-weighted. A learned/traveler strategy
replaces exactly this one function, consuming the per-edge tally as a feature;
everything else is unchanged.

Edge form: (src, tgt, kind, type) tuples, as in the clean-table carriers.
"""
from __future__ import annotations
import random
import collections


def _connected(edge, built_nodes):
    s, t, k, ty = edge
    return s in built_nodes or t in built_nodes


def _edge_weight(e, tally):
    m = tally['match'].get(e, 0)
    s = tally['stop'].get(e, 0)
    # base 1 (never zero -> soft), boosted by matches, damped by stops
    return (1.0 + 2.0 * m) / (1.0 + 3.0 * s)


def _choose_next(pool, tally, use_feedback, rng):
    """THE strategy seam. Blind: uniform. Feedback: soft tally-weighted.
    A traveler strategy replaces this function."""
    if use_feedback and len(pool) > 1:
        w = [_edge_weight(e, tally) for e in pool]
        return rng.choices(pool, weights=w, k=1)[0]
    return rng.choice(pool)


def build_sequence(edges, tally, use_feedback, rng):
    """One random connected-growth ordering of `edges`. Seeds a new component when
    no connected edge remains (this is what lets walks reach disconnected islands)."""
    remaining = list(edges)
    rng.shuffle(remaining)
    seq = []
    built = set()
    first = remaining.pop()
    seq.append(first)
    built |= {first[0], first[1]}
    while remaining:
        conn = [e for e in remaining if _connected(e, built)]
        pool = conn if conn else remaining
        e = _choose_next(pool, tally, use_feedback, rng)
        remaining.remove(e)
        seq.append(e)
        built |= {e[0], e[1]}
    return tuple(seq)


def agreement(seq, other_set):
    """Consecutive-from-start matched edges (a list, order preserved)."""
    matched = []
    for e in seq:
        if e in other_set:
            matched.append(e)
        else:
            break
    return matched


def find_core(src_edges, other_set, n_sequences=200, use_feedback=True, seed=0):
    """Grow a population of `n_sequences` distinct edge-walks over `src_edges`,
    matching against `other_set` (the edge set that the core must also be in —
    typically the intersection of the OTHER members). Returns:
        core         : frozenset of edges matched by ANY walk (the union)
        tally        : per-edge {'match','stop'} counters (the learned delta map)
        n_built      : number of distinct walks actually generated
    """
    rng = random.Random(seed)
    tally = {'match': collections.Counter(), 'stop': collections.Counter()}
    seen = set()
    union_matched = set()
    made = 0
    tries = 0
    cap = n_sequences * 50
    while made < n_sequences and tries < cap:
        tries += 1
        seq = build_sequence(src_edges, tally, use_feedback, rng)
        if seq in seen:
            continue
        seen.add(seq)
        made += 1
        matched = agreement(seq, other_set)
        union_matched |= set(matched)
        for e in matched:
            tally['match'][e] += 1
        for e in seq:
            if e not in other_set:
                tally['stop'][e] += 1
                break
    return frozenset(union_matched), tally, made


def core_and_deltas(member_edge_sets):
    """Convenience: given {name: set(edges)}, find the core (union-coverage against
    the intersection of all members) and each member's delta (edges not in core).
    Works for SHARED-ID members only (matching is id-based; see module docstring
    and test_idfree.py). For shared-id members this equals intersection-by-id."""
    names = list(member_edge_sets)
    # core must be present in ALL others; use intersection of all as the target so
    # the union-coverage core converges to the genuinely-shared edges.
    all_sets = list(member_edge_sets.values())
    target = set.intersection(*all_sets) if all_sets else set()
    # grow population from each member, union the cores (covers asymmetric cases)
    core = set()
    for nm in names:
        c, _, _ = find_core(list(member_edge_sets[nm]), target)
        core |= c
    deltas = {nm: set(member_edge_sets[nm]) - core for nm in names}
    return core, deltas
