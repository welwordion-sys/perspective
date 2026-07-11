"""reversed_rule.py — construct the inverse transition graph (graph2) for a
forward rule, per the settled design (KB: reversibility_classifier_design,
reversed_rule_placeholders):

  - NEW input side  = OLD output_nodes. Their internal structure
    (core.internal_edges, both direct-structural and marker-chain-encoded
    operational) becomes the new pattern's own internal relations.
  - NEW output side = OLD input_nodes.
  - Mapping edges reverse via core.mapping_in: an old (in_node -> out_node)
    mapping becomes a new (out_node -> in_node) mapping -- literally the
    same edge, source/target swapped, same real node objects.
  - Placeholders, per the confirmed AND-rule (ERS: reversed_placeholders_and_rule,
    empirically verified count=1 across 83 real rule instances, zero exceptions):
      * NEW-INPUT side (old outputs, now bind targets): for each (type,direction)
        category the OLD output node declared in its boundary_grab/preserve set,
        attach exactly ONE placeholder-connected edge of that category -- the
        same _typed_input_graph encoding used to build any forward input side.
      * NEW-OUTPUT side (old inputs, now producing survivors): for each
        (type,direction) category present in the OLD input's expected_crossing
        (view.expected_crossing keys, dropping counts -- the safe direction,
        already established), attach a boundary_decl preserve declaration
        (ph_all_four-style, but scoped to only the observed categories, not
        blanket all-four, since blanket-all-four would over-preserve beyond what
        the confirmed categories license).

Residual, NOT resolved here (carried from ERS sessions, see KB):
  - Only checked/tested against currently-existing rule families
    (add_finalise, add_finalise_multibit, addinit_v4, bitadd_v2, subinit_v1).
    bit_sub's full variant set is unauthored and unchecked.
  - This builds graph2 structurally. It does NOT yet wire into match_all /
    rebuild for an actual fire-and-recover round trip -- that is the next
    increment, not claimed done here.
"""
from __future__ import annotations
from basic_machinery.graph import PerspectiveGraph, Node, Edge, EdgeType
from basic_machinery.schema import compile_core, SchemaCore, _preserve_sets
from basic_machinery.transition_helpers import _marker


class NotReversibleError(Exception):
    """Raised by footprint_is_consistent() when a reversed rule's implied
    transformation footprint includes a position that was never recorded as
    transformed in the actual forward firing -- a direct, cheap proof of
    non-reversibility (Sven, this session), replacing the earlier wrong
    core.delete-based guard (see ers_corrected_locus, ers_supersession_audit)."""


def _attach_categories(g: PerspectiveGraph, node: Node, ph: Node, categories: set) -> None:
    """Attach one placeholder-connected edge per (EdgeType, 'in'|'out') category
    in `categories` to `node`, against shared placeholder `ph`. Mirrors
    transition_helpers._typed_input_graph's per-spec encoding, and
    boundary_decl.py's structural/operational cases -- but only for the
    categories actually present (never blanket all-four), per the AND-rule:
    a category's presence IS the count (=1), nothing more is asserted.
    """
    for (etype, direction) in categories:
        if etype == EdgeType.STRUCTURAL and direction == 'out':
            if Edge(node, ph, EdgeType.STRUCTURAL) not in g:
                g.add_edge(node, ph, EdgeType.STRUCTURAL)
        elif etype == EdgeType.STRUCTURAL and direction == 'in':
            if Edge(ph, node, EdgeType.STRUCTURAL) not in g:
                g.add_edge(ph, node, EdgeType.STRUCTURAL)
        elif etype == EdgeType.OPERATIONAL and direction == 'out':
            _marker(g, node, ph)
        elif etype == EdgeType.OPERATIONAL and direction == 'in':
            _marker(g, ph, node)
        else:
            raise ValueError(f"bad category for {node}: {(etype, direction)}")


def build_reversed_graph2(graph2: PerspectiveGraph, confirmed_crossings: dict = None):
    """Construct the inverse rule's graph2 from a forward rule's graph2.

    confirmed_crossings, if given (Sven, this session -- the physical-switch
    fix): out_node -> list[(EdgeType, direction, outside_real_node)], i.e.
    exactly _read_boundary_externals's output for ONE ACTUAL firing/binding.
    When provided, new-input categories are built from these CONFIRMED
    (exists AND declared) crossings instead of the blanket declared set
    (preserve/_preserve_sets, which only checks declaration, not existence --
    this was the root cause of the ph_all_four zero-match bug: a blanket
    ph_all_four declares 4 categories as POSSIBLE without guaranteeing any
    are present in a given real firing, so the exact-degree matcher's fixed
    requirement of all 4 fails whenever fewer are actually there). Passing
    confirmed_crossings makes the reversed pattern PER-BINDING rather than a
    single fixed pattern reused across all firings of the rule -- this does
    NOT reintroduce the "cheating" concern (using the forward binding to
    shortcut/bias the reverse search): it only corrects the pattern's
    REQUIREMENT to match what could actually be true, the resulting pattern
    still gets handed to a BLIND match_all with no seed_map (verified this
    session, ers_physical_switch_fix.json). If confirmed_crossings is None,
    falls back to the blanket declared set (the original, rule-level-only
    behavior -- valid for rules using only explicit, guaranteed-present
    single-category declarations, per the 83-instance survey, but NOT valid
    for rules using ph_all_four or similar blanket declarations).

    Returns (reversed_graph2, node_map) where node_map maps each ORIGINAL
    graph2 node (old input or old output) to its corresponding node in the
    reversed graph2 -- old outputs -> new input-side nodes, old inputs ->
    new output-side nodes. Markers and placeholders are NOT carried over
    (they are graph2-role-specific encodings, rebuilt fresh for the new role).

    Does NOT reject on core.delete. An earlier version raised NotReversibleError
    whenever core.delete was nonempty -- that was WRONG (ERS: ers_corrected_locus,
    ers_supersession_audit): core.delete/mapping_in/inherit is id-bookkeeping for
    in-place-rebuild footprint minimization, not a reversibility signal. Node
    identity carries no information (KB: node_identity_carries_no_information);
    correctness must be invariant to id choice. The actual reversibility check
    is footprint_is_consistent() below, a boundary/structural comparison against
    an ACTUAL firing's recorded transformation footprint -- not a static property
    of graph2 alone. build_reversed_graph2 always constructs the role-swapped
    graph2; whether that construction is VALID for a given firing is decided by
    footprint_is_consistent(), which needs a live firing to evaluate, not by
    anything checkable from graph2 in isolation.
    """
    core = compile_core(graph2)
    preserve = _preserve_sets(graph2, core.output_nodes, core.placeholders, core.markers)

    # We also need, for the OLD INPUT side, which (type,direction) categories
    # each bind target actually has a crossing declared for -- i.e. the same
    # information _preserve_sets computes for outputs, but for inputs. Reuse
    # derive_match_view's expected_crossing (already computed, categories only
    # needed -- drop the counts, per the confirmed safe direction).
    from basic_machinery.match_view import derive_match_view
    view = derive_match_view(graph2)

    g = PerspectiveGraph()
    node_map: dict[Node, Node] = {}

    # --- new input side = old output_nodes ---
    for old_out in core.output_nodes:
        node_map[old_out] = g.add_node()

    # --- new output side = old input_nodes ---
    for old_in in core.input_nodes:
        node_map[old_in] = g.add_node()

    # --- new input side's internal structure: old output_nodes' internal_edges ---
    for (src, tgt, et) in core.internal_edges:
        ns, nt = node_map[src], node_map[tgt]
        if et == EdgeType.STRUCTURAL:
            if Edge(ns, nt, EdgeType.STRUCTURAL) not in g:
                g.add_edge(ns, nt, EdgeType.STRUCTURAL)
        else:
            _marker(g, ns, nt)

    # --- new output side's internal structure: old input_nodes' OWN internal
    #     edges (self-loops encoding bit values, internal-to-pattern edges).
    #     BUG FOUND AND FIXED this session (Sven, via compute_unchanged_
    #     candidates catching it in actual use): this step was MISSING --
    #     old_in's own structure (e.g. a self-loop encoding bit value 1) was
    #     silently dropped, so the new output side lost information that
    #     should have been reconstructed. Symmetric to the new-input step
    #     above; reuses _input_internal_edges, the same helper
    #     compute_unchanged_candidates already uses. ---
    old_input_internal = _input_internal_edges(graph2, core.input_nodes, core.markers)
    for (src, tgt, et) in old_input_internal:
        ns, nt = node_map[src], node_map[tgt]
        if et == EdgeType.STRUCTURAL:
            if Edge(ns, nt, EdgeType.STRUCTURAL) not in g:
                g.add_edge(ns, nt, EdgeType.STRUCTURAL)
        else:
            _marker(g, ns, nt)

    # --- shared placeholder: ONE node serves both roles, exactly as every
    #     real rule in this codebase does (verified: spine_finalise_v1.py's
    #     ph_all_four reuses the SAME ph node _typed_input_graph returns for
    #     the input side). A placeholder is identified purely by its self-loop
    #     signature (structural + operational self-loop) in compile_core's
    #     _classify -- a second, signature-less node would not be recognized
    #     as a placeholder at all and would corrupt classification. ---
    new_input_categories: dict[Node, set] = {}
    if confirmed_crossings is not None:
        for old_out in core.output_nodes:
            cats = {(et, direction) for (et, direction, _outside)
                    in confirmed_crossings.get(old_out, [])}
            if cats:
                new_input_categories[node_map[old_out]] = cats
    else:
        new_input_categories = {
            node_map[old_out]: set(preserve.get(old_out, set()))
            for old_out in core.output_nodes if preserve.get(old_out)
        }
    new_output_categories: dict[Node, set] = {}
    for old_in in core.input_nodes:
        cats = set(view.expected_crossing.get(old_in, {}).keys())
        if cats:
            new_output_categories[node_map[old_in]] = cats

    ph = None
    if new_input_categories or new_output_categories:
        ph = g.add_node()
        g.add_edge(ph, ph, EdgeType.STRUCTURAL)
        g.add_edge(ph, ph, EdgeType.OPERATIONAL)
        for new_node, categories in new_input_categories.items():
            _attach_categories(g, new_node, ph, categories)
        for new_node, categories in new_output_categories.items():
            _attach_categories(g, new_node, ph, categories)

    # --- mapping edges: reverse core.inherit ONLY (Sven, this session --
    #     the actual bug: an earlier version reversed core.mapping_in, which
    #     includes EVERY fan-in candidate, winners AND losers. inherit is
    #     the WINNING/survived mapping alone, and it is guaranteed injective
    #     both directions (compile_core's own documented invariant: each
    #     input inherited by at most one output) -- reversing it needs no
    #     fan-in/fan-out handling at all. old inherit[out_node]=in_node
    #     becomes new_input(old_out) -> new_output(old_in).
    #
    #     This ALONE correctly handles born and delete with zero special-
    #     casing: a forward-BORN out_node has no inherit entry, so it gets
    #     no reverse mapping edge -- it stays a plain new-input context node
    #     with no output correspondence (nothing to recover, because nothing
    #     was inherited from it). A forward-DELETED in_node (zero-trace or
    #     a fan-in loser) is never an inherit VALUE either, so its new-output
    #     position also gets no reverse mapping edge -- it correctly stays
    #     unrecovered. That absence is not a defect to patch: it is exactly
    #     what should make the downstream footprint/isomorphism check catch
    #     genuine irreversibility (a position the true retained layer has,
    #     that the reconstruction cannot produce). No synthetic edges, no
    #     forced classification, no reverse-specific logic -- the reversed
    #     graph2 is just a graph2; compile_core classifies it the same way
    #     it classifies any other. ---
    for old_out, old_in in core.inherit.items():
        new_src = node_map[old_out]
        new_tgt = node_map[old_in]
        g.add_edge(new_src, new_tgt, EdgeType.OPERATIONAL)

    return g, node_map


def footprint_is_consistent(s_forward: set, s_reverse_implied: set) -> bool:
    """The reversibility pre-check (Sven, this session), replacing the wrong
    core.delete-based guard.

    s_forward:         the set of real-node positions actually recorded as
                        transformed by the FORWARD firing -- i.e. layer_apply_
                        schema's own `born | changed` for that firing. This is
                        a structural fact (differing edge sets), independent
                        of inherit-vs-born id choice (ers_corrected_locus).
    s_reverse_implied:  the analogous `born | changed` produced by firing the
                        ROLE-SWAPPED reversed rule (build_reversed_graph2)
                        against the actual result of the forward firing.

    Returns True iff s_reverse_implied is a SUBSET of s_forward: the reversed
    construction only claims to change positions that were actually recorded
    as having changed forward.

    NECESSARY, NOT SUFFICIENT. False is a hard, cheap proof of non-
    reversibility (the reversed construction demands changing something that
    provably never changed) -- no match_all / isomorphism check needed at all.
    True only licenses proceeding to refined_classifier's full check (flip the
    fired transition graph, require a distinct match, verify isomorphism to
    the retained previous layer) -- it does NOT itself establish reversibility.
    Conflating "passed this pre-check" with "is reversible" would be the same
    class of error as the discarded core.delete guard: a cheap necessary
    condition mistaken for the full answer.

    NOT YET WIRED: computing s_forward and s_reverse_implied from a real
    firing requires layer_apply_schema (or a variant) to expose born|changed
    for both the forward and the reversed direction against a live graph --
    that plumbing does not exist yet. This function is the correct, tested
    comparison logic; populating its two arguments from an actual firing is
    the next increment, not claimed done here.

    CAUTION, CORRECTED (Sven, this session): an earlier version of this
    docstring characterized compound same-region matches as something that
    could "corrupt" this check "for reasons unrelated to genuine source
    ambiguity" -- that was WRONG. refined_classifier's distinct-match
    requirement (match_all against the fired result, exactly one candidate
    reconstruction) has NO exception for where a competing match is found.
    ANY additional match -- to the same region ambiguously, to a genuinely
    different region, or as a side effect of a compound firing -- IS direct,
    first-class evidence against reversibility, not noise to filter or
    explain away. Discarding such a match post hoc would silently suppress
    the exact evidence the test exists to surface, producing a false
    REVERSIBLE verdict. The correct way to avoid spurious-seeming multi-region
    matches is to constrain the search correctly BEFORE running it -- via the
    anchor mechanism (ers_reversibility_anchor: pinning to a known-identity,
    untouched node) -- never to filter results after match_all returns them.
    This function still does not implement that anchoring or run any live
    match_all; it is noted here so the eventual live-firing implementation
    does not "fix" compound matches by excluding them.

    One narrower, separate, still-unresolved exception (carried, not solved
    here): a nontrivial automorphism in the reversed pattern could produce
    multiple bindings for the SAME underlying reconstruction rather than
    genuinely different candidate sources. That is a real distinct-match
    false-positive risk, but it is not the compound/outside-region case above,
    and is not addressed by this function either.
    """
    return s_reverse_implied <= s_forward


def _input_internal_edges(graph2: PerspectiveGraph, input_nodes: set, markers: set) -> set:
    """Mirrors compile_core's internal_edges computation (schema.py), but for
    the INPUT side -- not currently precomputed anywhere in SchemaCore.
    (Sven, this session: schema precomputation for bijective/unchanged nodes.)
    """
    from basic_machinery.schema import _decode_op_chain_targets
    internal = set()
    for e in graph2.edges:
        if e.edge_type == EdgeType.STRUCTURAL:
            if e.source in input_nodes and e.target in input_nodes:
                internal.add((e.source, e.target, EdgeType.STRUCTURAL))
    for src in input_nodes:
        for tgt in _decode_op_chain_targets(graph2, src, markers):
            if tgt in input_nodes:
                internal.add((src, tgt, EdgeType.OPERATIONAL))
    return internal


def _node_spectrum(node: Node, internal_edges: set) -> set:
    """(type, direction) categories an internal-edge set implies for `node`,
    from its own perspective. A self-loop counts as both 'in' and 'out'."""
    spectrum = set()
    for (src, tgt, et) in internal_edges:
        if src == node and tgt == node:
            spectrum.add((et, 'in')); spectrum.add((et, 'out'))
        elif src == node:
            spectrum.add((et, 'out'))
        elif tgt == node:
            spectrum.add((et, 'in'))
    return spectrum


def compute_unchanged_candidates(graph2: PerspectiveGraph) -> set:
    """Static, schema-level precomputation (Sven, this session): which
    (in_node, out_node) inherit pairs are CANDIDATES for 'unchanged' --
    bijectively mapped (core.inherit -- already guaranteed injective, no new
    work needed there, per compile_core's own documented invariant) AND
    whose DECLARED edge spectrum matches between input and output side
    (internal edges + expected_crossing/boundary_grab categories, compared
    per node).

    NECESSARY, NOT SUFFICIENT -- checked this session (ers_schema_precompute_
    unchanged.json): a declared-spectrum match does not guarantee the node is
    ACTUALLY unchanged for any given firing, because a blanket declaration
    (ph_all_four) can declare a category without it being present (the same
    gap that caused the earlier zero-match bug). Combine this static result
    with per-firing confirmed crossings (_read_boundary_externals) for a
    real per-firing verdict: a candidate is CONFIRMED-unchanged for a
    specific firing iff its confirmed crossings exactly equal its declared
    crossings (nothing merely-declared-but-absent this time).

    Returns set of (in_node, out_node) candidate pairs.
    """
    from basic_machinery.schema import compile_core
    from basic_machinery.match_view import derive_match_view

    core = compile_core(graph2)
    view = derive_match_view(graph2)
    input_internal = _input_internal_edges(graph2, core.input_nodes, core.markers)

    candidates = set()
    for out_node, in_node in core.inherit.items():
        out_spectrum = (_node_spectrum(out_node, core.internal_edges)
                        | {(et, direction) for (_in, et, direction) in core.boundary_grab.get(out_node, set())})
        in_spectrum = (_node_spectrum(in_node, input_internal)
                       | set(view.expected_crossing.get(in_node, {}).keys()))
        if in_spectrum == out_spectrum:
            candidates.add((in_node, out_node))
    return candidates
