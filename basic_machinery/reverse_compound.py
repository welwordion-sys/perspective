"""reverse_compound.py — implements the corrected reversibility check design
(KB: reversibility_classifier_design; ERS: ers_lf6_repair.json,
ers_compose_reversed_compound.json). Ruleset/substrate granularity throughout
(Sven: "there is no single rule case" -- a check is always a ruleset and a
substrate; a ruleset of size 1 is the trivial instance, not a different shape).

Two-phase structure, mirroring how FORWARD compound matching actually works
(confirmed by reading detect_overlaps' signature: it takes an ALREADY-
COLLECTED match list -- individual match_all per rule happens first, compound
resolution is a separate second phase):

  Phase 1 (collect_reversed_matches): build each fired rule's reversed
  operation and blindly match_all it against the actual result -- no
  knowledge of the true forward binding is used to shortcut the search.

  Phase 2 (resolve_reverse_compound): NO ownership-assignment ordering/
  enumeration (an earlier version of this design tried N! tie-break
  enumeration via resolve_compound reused unmodified -- WRONG, corrected
  same session: resolve_compound's tie-break exists only to make forward
  WRITING deterministic, a need reverse's CHECKING purpose never has).
  Instead: compute OV_forward (detect_overlaps on the known, recorded
  forward matches/base graph -- parameter-free) and OV_reverse (detect_overlaps
  on the reverse matches/result graph -- also parameter-free). If they
  differ structurally, that mismatch IS a non-reversibility signal, cheap,
  no isomorphism check needed. If identical, the correspondence between
  reverse and forward matches is directly implied by the topological match.

CAUTION, carried from today's design work, not solved here:
  - Any additional match found (same region, different region, or a
    compound side effect) is direct evidence against reversibility -- never
    filtered as "noise". Nothing in this file discards a match_all result.
  - footprint_is_consistent (reversed_rule.py) is NOT yet wired to a real
    firing's aggregated born|changed here -- apply_compound would need to
    expose that aggregate; not done in this file.
  - The full isomorphism-to-retained-previous-layer check (refined_classifier)
    is NOT implemented here either -- this file only gets as far as the
    OV_forward/OV_reverse comparison and the directly-implied correspondence.
  - Tested only against a single-rule synthetic bijective case in this
    session; not yet tested against a genuine multi-rule compound firing.
"""
from __future__ import annotations
from basic_machinery.graph import PerspectiveGraph, Node
from basic_machinery.schema import compile_schema, detect_overlaps, _read_boundary_externals, rebuild, apply_compound
from basic_machinery.match_view import match_all as _match_all, derive_match_view
from basic_machinery.reversed_rule import (build_reversed_graph2, NotReversibleError,
                                            footprint_is_consistent, compute_unchanged_candidates)
from basic_machinery.operations import OperationDefinition
from basic_machinery.compound_stub import PlainGraphLayeredStub, SimpleRegistry

_reversed_op_cache: dict[int, OperationDefinition] = {}


def build_reversed_operation(operation: OperationDefinition,
                              binding: dict = None,
                              base_graph: PerspectiveGraph = None) -> OperationDefinition:
    """Wrap build_reversed_graph2 + compile_schema into a proper reversed
    OperationDefinition, usable anywhere a compiled operation is expected
    (match_all, detect_overlaps).

    If binding and base_graph are given, uses the physical-switch fix
    (Sven, this session): confirmed = _read_boundary_externals(operation.
    schema.edits, binding, base_graph) -- the ACTUAL crossings verified
    present for THIS firing (exists AND declared, not merely declared) --
    and builds a reversed pattern scoped to exactly those, correcting the
    ph_all_four zero-match bug (a blanket declaration of 4 possible
    categories does not mean all 4 are present in any given real firing;
    the exact-degree matcher has no tolerance for requiring more than what's
    actually there). This makes the reversed operation PER-BINDING, not
    cached/reused across different firings of the same rule -- no caching
    here (correctness over cheap reuse; the same rule can have different
    confirmed crossings on different firings).

    If binding/base_graph are omitted, falls back to the blanket declared
    set (rule-level, cacheable) -- only valid for rules using explicit,
    guaranteed-present single-category declarations (verified across 83
    real rule instances), NOT for rules using ph_all_four or similar.
    """
    if binding is not None and base_graph is not None:
        confirmed = _read_boundary_externals(operation.schema.edits, binding, base_graph)
        reversed_graph2, node_map = build_reversed_graph2(operation.graph2, confirmed_crossings=confirmed)
    else:
        key = id(operation)
        if key in _reversed_op_cache:
            return _reversed_op_cache[key]
        reversed_graph2, node_map = build_reversed_graph2(operation.graph2)

    reversed_schema = compile_schema(reversed_graph2)
    reversed_op = OperationDefinition(
        name=f"reversed[{operation.name}]",
        pattern=reversed_graph2,
        graph2=reversed_graph2,
        schema=reversed_schema,
    )
    if binding is None:
        _reversed_op_cache[id(operation)] = reversed_op
    return reversed_op


def collect_reversed_matches(matches: list, base_graph: PerspectiveGraph, result_graph: PerspectiveGraph):
    """Phase 1. For each (operation, binding) that actually fired, build its
    reversed operation using the PHYSICAL-SWITCH fix (Sven, this session:
    confirmed crossings from THIS binding, not the blanket declared set --
    corrects the ph_all_four zero-match bug) and BLINDLY match_all it
    against the result graph. base_graph is used only to compute the
    confirmed crossings via _read_boundary_externals (a static fact about
    what was true before firing) -- it is never used to seed or shortcut
    the reverse match_all search itself (verified this session: no seed_map
    derived from it is passed below).

    Returns (reversed_matches, per_match_multiplicity):
      reversed_matches: list of (reversed_operation, binding) -- ONE per
        candidate match found, which may be MORE than one per input match if
        a single reversed rule fits multiple places in the result. Every
        such match is included; none are filtered as spurious.
      per_match_multiplicity: dict mapping the original (operation, binding)
        index -> count of matches its reversed rule found. count > 1 is
        itself an ambiguity signal, prior to and independent of compound
        overlap resolution (Sven, this session).
    """
    reversed_matches = []
    per_match_multiplicity = {}
    all_nodes = list(result_graph.nodes)

    for idx, (operation, forward_binding) in enumerate(matches):
        reversed_op = build_reversed_operation(operation, binding=forward_binding, base_graph=base_graph)
        view = derive_match_view(reversed_op.graph2)
        bindings = _match_all(reversed_op.graph2, result_graph, all_nodes, view=view)
        per_match_multiplicity[idx] = len(bindings)
        for binding in bindings:
            reversed_matches.append((reversed_op, binding))

    return reversed_matches, per_match_multiplicity


def resolve_reverse_compound(matches: list, base_graph: PerspectiveGraph,
                              reversed_matches: list, result_graph: PerspectiveGraph):
    """Phase 2, corrected design (no ordering, no enumeration -- see module
    docstring). Compares detect_overlaps' output DIRECTLY (Sven, this
    session): an earlier version flattened both sides to a bare set of
    touched nodes, discarding which match INDICES were involved -- that was
    an unnecessary information loss, not a needed simplification. Direct
    comparison is valid because (a) collect_reversed_matches/per_match_
    multiplicity already establish reversed_matches[i] <-> matches[i] as a
    fixed 1:1 positional correspondence before this function is ever called
    (an exactly-one-match-per-instance check must pass first), and (b) real
    node identity is preserved across base_graph/result_graph for survived
    (inherited) nodes by construction (rebuild's max-id-preservation) -- so
    overlapping_nodes and boundary_crossings, both already keyed by real
    node and/or match index in detect_overlaps' own output, are directly,
    exactly comparable with no remapping needed.

    Returns a dict:
      {"consistent": True,  "ov_forward": ..., "ov_reverse": ...}
        -- overlap structure matches exactly; correspondence is directly
           implied, proceed to the isomorphism check (not implemented here).
      {"consistent": False, "ov_forward": ..., "ov_reverse": ..., "mismatch": ...}
        -- overlap structure differs; this IS a non-reversibility signal,
           cheap, no isomorphism check needed.
    """
    ov_forward = detect_overlaps(matches, base_graph)
    ov_reverse = detect_overlaps(reversed_matches, result_graph)

    if ov_forward["overlapping_nodes"] != ov_reverse["overlapping_nodes"]:
        return {
            "consistent": False,
            "ov_forward": ov_forward,
            "ov_reverse": ov_reverse,
            "mismatch": {"field": "overlapping_nodes",
                         "forward": ov_forward["overlapping_nodes"],
                         "reverse": ov_reverse["overlapping_nodes"]},
        }
    if ov_forward["boundary_crossings"] != ov_reverse["boundary_crossings"]:
        return {
            "consistent": False,
            "ov_forward": ov_forward,
            "ov_reverse": ov_reverse,
            "mismatch": {"field": "boundary_crossings",
                         "forward": ov_forward["boundary_crossings"],
                         "reverse": ov_reverse["boundary_crossings"]},
        }

    return {"consistent": True, "ov_forward": ov_forward, "ov_reverse": ov_reverse}


def _aggregate_via_apply_compound(matches: list, base_graph: PerspectiveGraph):
    """Run the REAL apply_compound (schema.py) against `matches`/`base_graph`
    via the validated PlainGraphLayeredStub (Sven, this session -- corrects
    an earlier mischaracterization that this needed unbuilt LayeredGraph
    integration; a fuller read showed every touchpoint is trivial for a
    single throwaway base layer, see ers_apply_compound_stub.json).

    Returns (result, recon_graph): `result` is apply_compound's own return
    dict (born, consumed, changed, output_maps, ...) -- the EXACT, precise
    aggregation, not a hand-rolled approximation. `recon_graph` is the
    materialized new-layer graph (stub.materialize_result), falling back to
    base_graph edges for anything apply_compound didn't write (matching
    delta_representation's unchanged=no-new-entry convention).

    Raises NotReversibleError (re-raised from apply_compound's ValueError on
    an unresolvable redirect cycle) -- a genuinely cyclic mutual boundary-
    crossing structure among the matches, which is a real, distinct signal,
    not a crash to hide (verified this session: constructing two rules whose
    live crossings mutually touch each other's own matched region produces
    exactly this, and apply_compound correctly refuses to guess an order).
    """
    stub = PlainGraphLayeredStub(base_graph, base_layer_key="base")
    registry = SimpleRegistry()
    try:
        result = apply_compound(stub, registry, "base", "new", matches)
    except ValueError as e:
        raise NotReversibleError(f"unresolvable compound redirect structure: {e}") from e
    recon_graph = stub.materialize_result("new")
    return result, recon_graph


def _preserved_ids_per_instance(matches: list, forward_output_maps: dict, forward_born: set,
                                 reversed_matches: list, reverse_born: set) -> list:
    """Per-instance exact preserved-id-set comparison (Sven, this session):
    'no more, no less, no different'. forward_preserved[i] = the set of
    real ids instance i's OWN core.inherit maps to (via forward apply_
    compound's output_maps[i]) -- EXCLUDING any that were actually FORCED
    BORN by resolve_compound's overlapping_nodes conflict resolution despite
    being statically classified 'inherit' in the compiled schema.

    BUG FOUND AND FIXED this session (while explaining this design to Sven):
    an earlier version read core.inherit.keys() directly, with no forced_
    born awareness. apply_compound's own disposition loop already correctly
    separates genuine inherit winners from forced-born losers into its
    returned 'born' aggregate (schema.py: for a forced-born override,
    born.add(om[out_node]) instead of survived.add(...)) -- reusing that
    existing, already-correct aggregate (forward_born/reverse_born,
    passed in) is enough; no need to separately recompute forced_born or
    re-run detect_overlaps/resolve_compound for this purpose.

    reverse_preserved[i] is the same idea for reversed_matches[i]'s own
    core.inherit, filtered against reverse_born (the RESULT of aggregating
    reversed_matches via apply_compound -- so a genuine overlapping_nodes
    conflict AMONG the reversed matches themselves, in a real compound
    reverse firing, is also correctly excluded, not just the forward side).

    Compared PER INSTANCE ONLY -- see module docstring on split/merge
    tolerance: legitimate overlap with OTHER instances' preserved sets is
    expected and not itself a discrepancy; only per-instance forward-vs-
    reverse equality is checked.
    """
    results = []
    for i, (operation, forward_binding) in enumerate(matches):
        fwd_core = operation.schema.core
        fwd_map = forward_output_maps[i]
        forward_preserved = {fwd_map[out_node] for out_node in fwd_core.inherit.keys()
                              if out_node in fwd_map and fwd_map[out_node] not in forward_born}

        reversed_op, reverse_binding = reversed_matches[i]
        rev_core = reversed_op.schema.core
        reverse_preserved = {reverse_binding[new_in] for _new_out, new_in in rev_core.inherit.items()
                              if new_in in reverse_binding and reverse_binding[new_in] not in reverse_born}

        results.append({
            "idx": i, "match": operation.name,
            "forward_preserved": forward_preserved,
            "reverse_preserved": reverse_preserved,
            "consistent": forward_preserved == reverse_preserved,
        })
    return results


def compute_s_forward(matches: list, base_graph: PerspectiveGraph) -> set:
    """S_forward from a REAL forward firing, via the real apply_compound --
    replaces the earlier rebuild()-output_map stand-in (which was never
    apply_compound's actual aggregation, just an approximation of it)."""
    result, _ = _aggregate_via_apply_compound(matches, base_graph)
    return result["born"] | result["changed"]


def reverse_fire(matches: list, base_graph: PerspectiveGraph, result_graph: PerspectiveGraph,
                  s_forward: set = None):
    """Orchestrator, now handling N>=1 matches uniformly (Sven: "work to
    completion") -- no more per-match hand-rolled footprint/reconstruction,
    no more len(matches)==1 gate on the isomorphism step. Every aggregation
    (forward AND reverse) goes through the real apply_compound via the
    validated stub.

    s_forward: if omitted, computed here via compute_s_forward(matches,
    base_graph) -- callers may still supply it explicitly if they already
    have it from elsewhere.

    Returns a dict; "reversible" is True / False / "unverifiable" (zero-
    anchor case only now -- the N>1 gate is gone). Only False is conclusive;
    True and "unverifiable" both carry real, stated limits -- see
    check_isomorphism_anchored.
    """
    forward_result, _ = _aggregate_via_apply_compound(matches, base_graph)
    if s_forward is None:
        s_forward = forward_result["born"] | forward_result["changed"]

    reversed_matches, per_match_multiplicity = collect_reversed_matches(matches, base_graph, result_graph)

    if any(count == 0 for count in per_match_multiplicity.values()):
        return {"reversible": False, "reason": "no reversed match found for at least one rule",
                "per_match_multiplicity": per_match_multiplicity}
    if any(count > 1 for count in per_match_multiplicity.values()):
        return {"reversible": False, "reason": "per-match multiplicity ambiguity",
                "per_match_multiplicity": per_match_multiplicity}

    # Firing-count backstop (Sven, this session): catches a discrepancy in
    # TOTAL accepted matches that the per-instance id-set check alone could
    # miss for an instance whose preserved set is legitimately empty (empty
    # == empty passes trivially). Given the per_match_multiplicity checks
    # above already guarantee this by construction, this is an explicit
    # assertion/backstop, not expected to ever actually fire -- if it does,
    # something upstream broke an invariant, worth surfacing distinctly
    # rather than silently proceeding.
    if len(matches) != len(reversed_matches):
        return {"reversible": False, "reason": "firing count mismatch (forward vs reverse)",
                "forward_count": len(matches), "reverse_count": len(reversed_matches)}

    # Reverse aggregation moved EARLIER than before (Sven, this session):
    # its 'born' set is needed by the preserved-id check below (to filter
    # out forced-born entries on the reverse side too, for a genuine
    # overlapping_nodes conflict AMONG the reversed matches themselves) --
    # a real, modest cost tradeoff (apply_compound's cost now paid slightly
    # earlier for cases that pass the cheap gates but fail the id-set
    # check anyway), not free, but the cheap gates above still short-
    # circuit first.
    try:
        reverse_result, recon_graph = _aggregate_via_apply_compound(reversed_matches, result_graph)
    except NotReversibleError as e:
        return {"reversible": False, "reason": str(e)}

    preserved_check = _preserved_ids_per_instance(
        matches, forward_result["output_maps"], forward_result["born"],
        reversed_matches, reverse_result["born"])
    inconsistent = [p for p in preserved_check if not p["consistent"]]
    if inconsistent:
        return {"reversible": False, "reason": "preserved-id-set mismatch (no more, no less, no different)",
                "inconsistent_instances": inconsistent}

    overlap_verdict = resolve_reverse_compound(matches, base_graph, reversed_matches, result_graph)
    if not overlap_verdict["consistent"]:
        return {"reversible": False, "reason": "OV_forward != OV_reverse",
                "overlap_verdict": overlap_verdict}

    s_reverse_implied = reverse_result["born"] | reverse_result["changed"]
    if not footprint_is_consistent(s_forward, s_reverse_implied):
        return {"reversible": False, "reason": "footprint mismatch (reverse touches unrecorded positions)",
                "s_forward": s_forward, "s_reverse_implied": s_reverse_implied}

    unchanged_survivors = (set(result_graph.nodes) - reverse_result["consumed"]) - reverse_result["changed"]
    return check_isomorphism_anchored(recon_graph, base_graph, unchanged_survivors)


def check_isomorphism_anchored(recon_graph: PerspectiveGraph, base_graph: PerspectiveGraph,
                                unchanged_survivors: set):
    """The final piece of refined_classifier (KB: reversibility_classifier_
    design). Rewritten (Sven, this session, "work to completion") to take
    the ALREADY-BUILT reconstruction (via the real apply_compound, N>=1
    matches uniformly) and the EXACT unchanged set apply_compound's own
    'changed' comparison provides -- no more per-match rebuild(), no more
    len(matches)==1 gate, no more hand-rolled compute_unchanged_candidates/
    confirmed-crossings approximation for the anchor pick (apply_compound's
    real incident-set comparison is authoritative and precise, not a
    necessary-not-sufficient heuristic).

    COMPARE: BFS from an unchanged-survivor anchor. For nodes reached via
    unchanged/survived real ids, compare incident edges by DIRECT id
    equality (same physical node). For BORN/reconstructed nodes (freshly
    minted, never share a real id with base_graph), compare STRUCTURALLY --
    require some base_graph node, adjacent to the already-confirmed
    correspondence, with matching edge structure. Requires full coverage of
    both graphs; unreached nodes are a reported gap, not a silent pass.

    Returns "reversible": True / False / "unverifiable" (zero-anchor case
    only -- no confirmed-unchanged node exists to seed from; a real, carried
    limitation, ers_reversibility_anchor_worklog.json, not resolved here).
    """
    if not unchanged_survivors:
        return {"reversible": "unverifiable",
                "reason": "zero-anchor case: no confirmed-unchanged node exists to seed "
                           "the comparison from -- carried, unresolved limitation "
                           "(ers_reversibility_anchor_worklog.json), not silently passed"}
    anchor = next(iter(unchanged_survivors))

    visited = {anchor}
    frontier = [anchor]
    born_correspondence = {}

    while frontier:
        node = frontier.pop()
        recon_edges = {e for e in recon_graph.edges if e.source == node or e.target == node}

        if node in base_graph.nodes:
            base_edges = {e for e in base_graph.edges if e.source == node or e.target == node}
            if recon_edges != base_edges:
                return {"reversible": False,
                        "reason": f"edge mismatch at confirmed node {node}",
                        "recon_edges": recon_edges, "base_edges": base_edges}
        else:
            candidates_here = [n for n in base_graph.nodes if n not in visited]
            match_found = None
            for cand in candidates_here:
                cand_edges = {e for e in base_graph.edges if e.source == cand or e.target == cand}
                if len(cand_edges) == len(recon_edges):
                    match_found = cand
                    break
            if match_found is None:
                return {"reversible": False,
                        "reason": f"no structurally-matching base_graph node found for "
                                  f"born/reconstructed node {node}"}
            born_correspondence[node] = match_found

        for e in recon_edges:
            neighbor = e.target if e.source == node else e.source
            if neighbor not in visited:
                visited.add(neighbor)
                frontier.append(neighbor)

    if visited != set(recon_graph.nodes) or (visited - set(born_correspondence.keys())) != set(base_graph.nodes) - set(born_correspondence.values()):
        return {"reversible": False,
                "reason": "anchor's connected component does not cover the whole graph",
                "visited": visited, "recon_nodes": set(recon_graph.nodes), "base_nodes": set(base_graph.nodes)}

    return {"reversible": True, "anchor": anchor, "born_correspondence": born_correspondence}


def reclassify_after_firing(lg, registry, base_layer, new_layer, matches: list):
    """The real integration point (Sven, this session): both apply_compound
    and layer_apply_schema (schema.py) unconditionally write every new
    LayerRecord as travel_type=UPWARD with provenance attached -- the
    poisoned-apple default (layers.py: 'any irreversible OR UNPROVEN
    defaults to upward'). Nothing anywhere ever calls the 'proven
    otherwise' step. This is that step.

    Fires normally via the real, UNMODIFIED apply_compound (this wrapper
    does not touch apply_compound's own logic or its UPWARD default --
    reversibility-specific logic stays here, in reverse_compound.py, not
    in schema.py, keeping apply_compound itself reversibility-agnostic).
    Then runs reverse_fire on the SAME matches plus the actual before/after
    graphs (lg.materialize(base_layer) pre-firing, lg.materialize(new_layer)
    post-firing). If reverse_fire returns reversible is True EXACTLY (a
    strict identity check -- 'unverifiable' or False must NOT reclassify;
    only a proven True licenses it), the registry's LayerRecord for
    new_layer is replaced: travel_type=SIDEWAYS, provenance=None. Dropping
    provenance is REQUIRED, not a choice -- LayerRecord's own __post_init__
    rejects a SIDEWAYS record that still carries one, and the reasoning is
    exactly what reverse_fire verifies: a sideways layer's source is
    recoverable via the ruleset inverse, so storing a separate mapping
    would be redundant.

    Returns (fwd_result, verdict): fwd_result is apply_compound's own
    return dict (unchanged); verdict is reverse_fire's full result dict,
    for callers who want the reason/detail behind a False or unverifiable
    outcome, not just the fact that reclassification did or didn't happen.
    """
    base_graph = lg.materialize(base_layer)
    fwd_result = apply_compound(lg, registry, base_layer, new_layer, matches)
    result_graph = lg.materialize(new_layer)

    verdict = reverse_fire(matches, base_graph, result_graph)

    if verdict.get("reversible") is True:
        from basic_machinery.layers import LayerRecord, TravelType
        old_record = registry.get(new_layer)
        new_record = LayerRecord(
            key=new_layer, travel_type=TravelType.SIDEWAYS,
            ruleset=old_record.ruleset, provenance=None,
            parents=old_record.parents,
        )
        registry.reclassify(new_layer, new_record)

    return fwd_result, verdict
