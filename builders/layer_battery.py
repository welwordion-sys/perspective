"""
layer_battery.py — stress test for the LayeredGraph path.

For each addition a+b (0..7 x 0..7):
  1. Encode a+b=<expected> into a PerspectiveGraph.
  2. Run the same graph through apply() step-by-step to get the oracle
     final state (flat graph).
  3. Run via apply_to_layer() step-by-step on a fresh LayeredGraph,
     advancing layer keys 0 -> 1 -> 2 -> ...
  4. After each layer:
       - validate()                     double-recording invariant
       - roster_ok()                    consumed absent, born present
       - no_stale_edges()               no roster-present node holds an
                                        edge to a consumed node
       - provenance_complete()          every base node MAPPED or CONSUMED,
                                        every result node MAPPED or BORN
  5. After the final layer:
       - graph_equiv()                  materialize(final) == oracle edge-set

Prints per-case results and a summary. Exit 1 on any failure.
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from basic_machinery.graph import PerspectiveGraph, Node, Edge, EdgeType
from basic_machinery.encoding import encode
from basic_machinery.operations import apply, apply_to_layer, OperationDefinition
from basic_machinery.layers import LayeredGraph, LayerRegistry, LayerRecord, TravelType

# Register all arithmetic rules
import arithmetic_spine
arithmetic_spine.register_all()

from basic_machinery.operations import _registry

import os

MAX_STEPS = 40  # upper bound on rewrite steps per case


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def seed_layer(lg: LayeredGraph, g: PerspectiveGraph, layer_key) -> None:
    """Populate layer 0 of a fresh LayeredGraph from a flat PerspectiveGraph.
    Sets an explicit roster (required for derive_roster to work correctly) and
    writes each node's incident edge set."""
    for n in g.nodes:
        lg.adopt_node(n)
    lg.set_roster(layer_key, g.nodes)
    for n in g.nodes:
        incident = {e for e in g.edges if e.source == n or e.target == n}
        lg.set_edges(n, layer_key, incident)


#: Grouped dispatch statt per-rule match-all. Siehe grouping/matcher.py.
#: KB layer_battery_slow: "apply_to_layer iterates all 257 registered rules per
#: step until one fires ... Full 64-case battery times out at 90s."
#: KB reversibility_classifier_design.ers_audit: der fingerprint-gate wurde
#: getestet und brachte NULL nutzen (0/257 regeln uebersprungen); "real pruning
#: would require leveraging CoreTree's shared-core walk ... which was not
#: attempted." Genau das macht Matcher jetzt: gemessen 2.27x, 167 statt 2921
#: invocations, 4544 uebersprungene regelversuche, 0 mismatches.
#: Default AUS: einschalten via USE_GROUPED_DISPATCH oder env PERSPECTIVE_GROUPED=1.
USE_GROUPED_DISPATCH = os.environ.get('PERSPECTIVE_GROUPED', '') == '1'

_MATCHER = None


def _matcher():
    """Lazy: der baum wird einmal gebaut/geladen, nicht pro lauf.

    WICHTIG list(_registry) statt sorted(): die registry-reihenfolge ist NICHT
    sortiert (erste eintraege: add_zero_collapse, mul_one_collapse, ...). Da
    bei mehreren treffern die ERSTE regel feuert, wuerde sorted() eine andere
    regel waehlen als der loop — das waere eine verhaltensaenderung, kein
    speedup. Gemessen mit list(_registry): 51 schritte, 0 abweichungen.
    """
    global _MATCHER
    if _MATCHER is None:
        import os.path as _op
        from matcher import Matcher
        _MATCHER = Matcher(list(_registry),
                           tree_path=_op.join(_op.dirname(_op.dirname(
                               _op.abspath(__file__))), 'grouping',
                               'registry_tree.json'))
    return _MATCHER


def find_firing_rule(g: PerspectiveGraph):
    """Name der feuernden Regel, oder None. Trennt SUCHE von ANWENDUNG.

    Der alte pfad verschmilzt beides: apply() wird probiert und bei
    fehlschlag zurueckgerollt (g.copy() + restore pro regel). Grouped
    dispatch kann nur greifen, wenn die suche eigenstaendig ist.
    """
    if USE_GROUPED_DISPATCH:
        return _matcher().dispatch(g)
    for nm, op in _registry.items():
        snap = g.copy()
        if apply(g, op):
            g.restore(snap)
            return nm
        g.restore(snap)
    return None


def oracle_run(g: PerspectiveGraph) -> PerspectiveGraph | None:
    """Drive g to completion via apply(), return final graph or None on timeout."""
    for _ in range(MAX_STEPS):
        nm = find_firing_rule(g)
        if nm is None:
            return g
        apply(g, _registry[nm])
    return None  # did not terminate


def layer_run(lg: LayeredGraph, registry: LayerRegistry, base: int
              ) -> tuple[int, list[str]]:
    """Drive lg to completion via apply_to_layer, starting from layer `base`.
    Returns (final_layer_key, list_of_errors)."""
    errors = []
    current = base

    for step in range(MAX_STEPS):
        next_layer = current + 1

        if USE_GROUPED_DISPATCH:
            # SUCHE getrennt von ANWENDUNG. Der alte loop rief
            # apply_to_layer pro regel; das materialisiert intern
            # lg.materialize(base_layer) JEDES MAL neu (schema.py:492) und
            # matcht dann (schema.py:497). Bei 257 regeln pro schritt ist das
            # 257 materialisierungen + 257 matches, nur um EINE feuernde regel
            # zu finden. Grouped dispatch sucht auf EINEM materialisierten
            # graph und wendet dann genau die gewinner-regel an.
            # Gefahrlos, weil layer_apply_schema bei binding is None sofort
            # None zurueckgibt, BEVOR es schreibt (schema.py:498) — ein
            # fehlversuch hinterlaesst keine layer.
            base = lg.materialize(current)
            nm = _matcher().dispatch(base)
            if nm is None:
                break
            res = apply_to_layer(lg, registry, current, next_layer,
                                 _registry[nm])
            if not res.fired:
                # darf nicht vorkommen: dispatch ist aequivalent zu
                # match_cut_at_edge, das layer_apply_schema selbst benutzt.
                errors.append(
                    f"step {step}: dispatch picked {nm} but apply_to_layer "
                    f"did not fire — dispatch/match divergence")
                break
            errs = check_layer(lg, registry, current, next_layer, res)
            errors.extend(errs)
            current = next_layer
            continue

        fired = False
        for op in _registry.values():
            res = apply_to_layer(lg, registry, current, next_layer, op)
            if res.fired:
                errs = check_layer(lg, registry, current, next_layer, res)
                errors.extend(errs)
                current = next_layer
                fired = True
                break
        if not fired:
            break

    return current, errors


# ---------------------------------------------------------------------------
# Per-layer checks
# ---------------------------------------------------------------------------

def check_layer(lg: LayeredGraph, reg: LayerRegistry,
                base_layer, new_layer, res) -> list[str]:
    errs = []

    # 1. double-recording
    problems = lg.validate(new_layer)
    for p in problems:
        errs.append(f"  [validate] {p}")

    # 2. roster: consumed absent, born present
    new_roster = lg.roster(new_layer)
    for n in res.consumed:
        if n in new_roster:
            errs.append(f"  [roster] consumed node {n.id} still in child roster")
    for n in res.born:
        if n not in new_roster:
            errs.append(f"  [roster] born node {n.id} missing from child roster")

    # 3. no stale edges — roster-present nodes must not hold edges to consumed nodes
    for n in new_roster:
        for e in lg.edges_of(n, new_layer):
            other = e.target if e.source == n else e.source
            if other in res.consumed:
                errs.append(
                    f"  [stale_edge] node {n.id} holds edge to consumed {other.id} "
                    f"at layer {new_layer}"
                )

    # 4. provenance completeness — only consumed and born nodes must appear.
    # Bystanders (roster nodes outside the rule match window) are implicitly
    # identity-mapped and correctly have no provenance entry.
    prov = res.provenance
    if prov is not None:
        sourced  = {e.source for e in prov.entries if e.source is not None}
        resulted = {e.result for e in prov.entries if e.result is not None}
        for n in res.consumed:
            if n not in sourced:
                errs.append(f"  [provenance] consumed node {n.id} has no provenance entry")
        for n in res.born:
            if n not in resulted:
                errs.append(f"  [provenance] born node {n.id} has no provenance entry")

    return errs


# ---------------------------------------------------------------------------
# Final equivalence check
# ---------------------------------------------------------------------------

def graph_equiv(g_oracle: PerspectiveGraph, g_layer: PerspectiveGraph) -> list[str]:
    """Compare edge sets of two graphs, ignoring node id assignment.
    Strategy: canonical edge signature = sorted tuple of (s_degree, t_degree)
    per edge, where degree = (s_out, s_in, s_self, o_out, o_in, o_self).
    Two graphs are equivalent iff their multisets of canonical edge signatures match.
    This is id-invariant (node ids are meaningless) but catches structural differences.
    """
    errs = []

    def fp(n, g):
        s_out = sum(1 for e in g.edges_from(n, EdgeType.STRUCTURAL) if e.target != n)
        s_in  = sum(1 for e in g.edges_to(n,   EdgeType.STRUCTURAL) if e.source != n)
        s_sl  = 1 if Edge(n, n, EdgeType.STRUCTURAL) in g else 0
        o_out = sum(1 for e in g.edges_from(n, EdgeType.OPERATIONAL) if e.target != n)
        o_in  = sum(1 for e in g.edges_to(n,   EdgeType.OPERATIONAL) if e.source != n)
        o_sl  = 1 if Edge(n, n, EdgeType.OPERATIONAL) in g else 0
        return (s_out, s_in, s_sl, o_out, o_in, o_sl)

    def edge_sig(e, g):
        sfp = fp(e.source, g)
        tfp = fp(e.target, g)
        return (e.edge_type.value, tuple(sorted([sfp, tfp])))

    oracle_sigs = sorted(edge_sig(e, g_oracle) for e in g_oracle.edges)
    layer_sigs  = sorted(edge_sig(e, g_layer)  for e in g_layer.edges)

    if oracle_sigs != layer_sigs:
        errs.append(
            f"  [graph_equiv] edge multisets differ: "
            f"oracle={len(oracle_sigs)} edges, layer={len(layer_sigs)} edges"
        )
        # detail: find first mismatch
        for i, (o, l) in enumerate(zip(oracle_sigs, layer_sigs)):
            if o != l:
                errs.append(f"    first diff at index {i}: oracle={o} layer={l}")
                break
        if len(oracle_sigs) != len(layer_sigs):
            extra_o = sorted(set(oracle_sigs) - set(layer_sigs))
            extra_l = sorted(set(layer_sigs) - set(oracle_sigs))
            if extra_o: errs.append(f"    in oracle only: {extra_o[:3]}")
            if extra_l: errs.append(f"    in layer only:  {extra_l[:3]}")

    return errs


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_case(a: int, b: int) -> tuple[bool, list[str], int]:
    """Returns (passed, errors, num_layers)."""
    expected = a + b
    expr = f"{a}+{b}={expected}"
    all_errors = []

    # --- oracle ---
    g_oracle = PerspectiveGraph()
    encode(g_oracle, expr)
    g_flat = PerspectiveGraph()
    encode(g_flat, expr)
    result = oracle_run(g_flat)
    if result is None:
        return False, [f"  [oracle] did not terminate in {MAX_STEPS} steps"], 0

    # --- layer path ---
    g_seed = PerspectiveGraph()
    encode(g_seed, expr)
    lg = LayeredGraph()
    reg = LayerRegistry()
    seed_layer(lg, g_seed, layer_key=0)

    final_layer, layer_errors = layer_run(lg, reg, base=0)
    all_errors.extend(layer_errors)

    # --- equivalence ---
    g_materialized = lg.materialize(final_layer)
    equiv_errors = graph_equiv(result, g_materialized)
    all_errors.extend(equiv_errors)

    return len(all_errors) == 0, all_errors, final_layer


if __name__ == '__main__':
    total = passed = 0
    all_failures = []

    for a in range(8):
        for b in range(8):
            total += 1
            ok, errs, n_layers = run_case(a, b)
            if ok:
                passed += 1
            else:
                all_failures.append((a, b, errs, n_layers))
                print(f"FAIL {a}+{b}  ({n_layers} layers)")
                for e in errs:
                    print(e)

    print(f"\n{passed}/{total} cases passed")
    if all_failures:
        print(f"{len(all_failures)} failures")
        sys.exit(1)
    else:
        print("ALL PASS")
