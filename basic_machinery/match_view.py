from __future__ import annotations
from dataclasses import dataclass, field
from basic_machinery.graph import PerspectiveGraph, Node, Edge, EdgeType


# ---------------------------------------------------------------------------
# Cut-at-edge match-view derivation
#
# The match view is DERIVED from the input graph (graph2's input side), not
# from a separate operation.pattern — so there is no second representation to
# drift from under GA mutation.
#
# Model (settled over design sessions kb-reframe..this):
#   - The match constraint is the real node's TOTAL degree per (type, direction)
#     — internal edges plus crossing (boundary) edges. This total IS the cut.
#   - Input placeholders make the input graph's per-node degree equal that real
#     total: each crossing edge a boundary node has is represented by one
#     placeholder edge of the matching (type, direction). Counting the input
#     graph's degree (placeholder edges included) therefore yields the expected
#     real total degree.
#   - A placeholder is identified by its signature: a node carrying BOTH a
#     structural and an operational self-loop. No real graph node has this, which
#     is exactly why it is a reliable discriminator. The signature is NOT a
#     failure — the earlier defect was carrying placeholders into the match view
#     AS BIND TARGETS (then the real graph cannot bind the unmatchable signature).
#     The fix is here, in derivation: a placeholder is consumed into its
#     neighbour's expected degree and never emitted as a bind target.
#   - Mapping edges (input->output OPERATIONAL instructions) are NOT part of the
#     matchable architecture and must be excluded from the derived view.
#   - Output side: a SINGLE shared output placeholder acts as a boolean gate
#     marking which output nodes receive external edges. It does not pair, count,
#     or position anything. The reference list does all external-edge transport.
# ---------------------------------------------------------------------------


def _has_signature(node: Node, g: PerspectiveGraph) -> bool:
    """Placeholder signature: both a structural and an operational self-loop."""
    return (
        Edge(node, node, EdgeType.STRUCTURAL) in g
        and Edge(node, node, EdgeType.OPERATIONAL) in g
    )


# A degree key is (edge_type, direction) where direction is 'out' or 'in'
DegreeKey = tuple


@dataclass
class MatchView:
    """
    Derived matchable view of an input graph.

    bind_targets:   input-graph nodes the matcher must bind to real nodes.
                    Placeholders and markers are excluded.
    expected_degree: per bind target, the expected real TOTAL degree, keyed by
                    (edge_type, 'out'|'in'). This already folds in placeholder
                    edges, so it equals the real node's full degree (the cut).
    """
    bind_targets: set[Node] = field(default_factory=set)
    expected_degree: dict[Node, dict[DegreeKey, int]] = field(default_factory=dict)
    # expected CROSSING degree per bind target: the component of expected_degree
    # that goes to placeholders (i.e. leaves the matched region). Kept separate so
    # the matcher can require the internal/crossing SPLIT to match, not just the
    # total. Without this, a real node satisfies an expected-internal slot with a
    # crossing edge (e.g. a result spine whose 2nd OP-out leaves the region),
    # matching a variant it should not. expected_degree stays the TOTAL (cut-at-edge
    # design preserved); this only restores the split derivation threw away.
    expected_crossing: dict[Node, dict[DegreeKey, int]] = field(default_factory=dict)


def _is_mapping_edge(edge: Edge, markers: set[Node], placeholders: set[Node]) -> bool:
    """
    A mapping edge is an OPERATIONAL input->output instruction edge: operational,
    non-self-loop, and not part of a marker chain or placeholder structure.
    Marker self-loops and placeholder self-loops are operational but are NOT
    mapping edges. We exclude any operational edge whose endpoints are markers or
    placeholders, plus self-loops.
    """
    if edge.edge_type != EdgeType.OPERATIONAL:
        return False
    if edge.source == edge.target:
        return False
    if edge.source in markers or edge.target in markers:
        return False
    if edge.source in placeholders or edge.target in placeholders:
        return False
    return True



def _marker_chain_far(node, m, input_graph):
    """Far endpoints of the marker chain hanging off `node` through marker `m`.
    For out: node ->S-> m ->S-> X  => returns X's. For in: X ->S-> m ->S-> node."""
    outs = [e.target for e in input_graph.edges_from(m, EdgeType.STRUCTURAL)
            if e.target != m and e.target != node]
    ins  = [e.source for e in input_graph.edges_to(m, EdgeType.STRUCTURAL)
            if e.source != m and e.source != node]
    return outs, ins


def derive_match_view(input_graph: PerspectiveGraph) -> MatchView:
    """
    Derive the cut-at-edge match view from an input graph.

    Steps:
      1. Identify placeholders (signature) and markers (operational self-loop only).
      2. Bind targets = all other nodes.
      3. For each bind target, compute expected real total degree per
         (type, direction) by counting its incident edges in the input graph —
         INCLUDING edges to placeholders (those are the crossing edges), EXCLUDING
         mapping edges, marker self-loops, and placeholder self-loops.
    """
    placeholders: set[Node] = set()
    markers: set[Node] = set()
    for n in input_graph.nodes:
        has_s = Edge(n, n, EdgeType.STRUCTURAL) in input_graph
        has_o = Edge(n, n, EdgeType.OPERATIONAL) in input_graph
        if has_s and has_o:
            placeholders.add(n)
        elif has_o:
            markers.add(n)

    # Input/output split — mirrors _apply_pass step 2. Output-only nodes are the
    # targets of mapping edges that are never themselves sources. Bind targets are
    # INPUT-side only: the match view must be derived from the input side, never
    # the output half of the transition.
    has_outgoing: set[Node] = set()
    has_incoming: set[Node] = set()
    for e in input_graph.edges:
        if e.edge_type == EdgeType.OPERATIONAL and e.source != e.target:
            has_outgoing.add(e.source)
            has_incoming.add(e.target)
    output_only = has_incoming - has_outgoing

    bind_targets = set(input_graph.nodes) - placeholders - markers - output_only

    view = MatchView(bind_targets=set(bind_targets))

    for n in bind_targets:
        deg: dict[DegreeKey, int] = {}
        cross: dict[DegreeKey, int] = {}
        # A structural self-loop on a bind target is a REAL edge (bit value 1),
        # not an encoding signal, and must count toward total degree. Operational
        # self-loops belong to markers/placeholders (not bind targets) and are
        # excluded by virtue of those nodes not being bind targets.
        if Edge(n, n, EdgeType.STRUCTURAL) in input_graph:
            deg[(EdgeType.STRUCTURAL, 'self')] = 1
        # Out edges
        for e in input_graph.edges_from(n):
            if e.source == e.target:
                continue  # self-loop handled above
            if _is_mapping_edge(e, markers, placeholders):
                continue
            # An edge to a marker is the FIRST hop of a marker chain encoding a
            # real OPERATIONAL crossing/edge. Count it as one operational-out.
            if e.target in markers:
                k = (EdgeType.OPERATIONAL, 'out')
                deg[k] = deg.get(k, 0) + 1
                fouts, _ = _marker_chain_far(n, e.target, input_graph)
                if any(x in placeholders for x in fouts):
                    cross[k] = cross.get(k, 0) + 1
                continue
            key = (e.edge_type, 'out')
            deg[key] = deg.get(key, 0) + 1
            if e.target in placeholders:
                cross[key] = cross.get(key, 0) + 1
        # In edges
        for e in input_graph.edges_to(n):
            if e.source == e.target:
                continue
            if _is_mapping_edge(e, markers, placeholders):
                continue
            if e.source in markers:
                k = (EdgeType.OPERATIONAL, 'in')
                deg[k] = deg.get(k, 0) + 1
                _, fins = _marker_chain_far(n, e.source, input_graph)
                if any(x in placeholders for x in fins):
                    cross[k] = cross.get(k, 0) + 1
                continue
            key = (e.edge_type, 'in')
            deg[key] = deg.get(key, 0) + 1
            if e.source in placeholders:
                cross[key] = cross.get(key, 0) + 1
        view.expected_degree[n] = deg
        view.expected_crossing[n] = cross

    return view


# ---------------------------------------------------------------------------
# Real-graph degree and the cut-at-edge match decision
# ---------------------------------------------------------------------------

def real_total_degree(node: Node, graph: PerspectiveGraph) -> dict[DegreeKey, int]:
    """
    Total degree of a real node per (type, direction) — internal AND crossing
    edges, undifferentiated. This total is the cut-at-edge constraint: the match
    binds a node iff its full degree equals the derived expected degree. A
    structural self-loop (bit value 1) counts; that is real structure.
    """
    deg: dict[DegreeKey, int] = {}
    if Edge(node, node, EdgeType.STRUCTURAL) in graph:
        deg[(EdgeType.STRUCTURAL, 'self')] = 1
    for e in graph.edges_from(node):
        if e.source == e.target:
            continue
        key = (e.edge_type, 'out')
        deg[key] = deg.get(key, 0) + 1
    for e in graph.edges_to(node):
        if e.source == e.target:
            continue
        key = (e.edge_type, 'in')
        deg[key] = deg.get(key, 0) + 1
    return deg


def degree_matches(view: MatchView, t_node: Node, real_node: Node,
                   graph: PerspectiveGraph) -> bool:
    """
    Cut-at-edge match decision for one node pairing: the real node's TOTAL degree
    must equal the bind target's derived expected degree (which already folds in
    placeholder crossings). Replaces _exact_count_ok's internal-only filtering.
    """
    return real_total_degree(real_node, graph) == view.expected_degree[t_node]


# ---------------------------------------------------------------------------
# Cut-at-edge matcher over a derived match view
#
# Integrates the degree-based decision into a VF2-style structural backtracking
# search. Differences from the legacy _vf2_match + _exact_count_ok:
#   - Bind targets come from the derived view (placeholders/markers excluded).
#   - Internal edge-consistency understands marker chains: an input-graph
#     operational relation A->B is encoded as A->[S]->m->[S]->B with m an
#     operational self-loop, so a direct operational edge between two bind
#     targets in the REAL graph satisfies it.
#   - Acceptance uses degree_matches against the FULL real graph (so crossing
#     edges count), not an internal-only subgraph count.
# ---------------------------------------------------------------------------

def _input_relations(input_graph: PerspectiveGraph, view: MatchView):
    """
    Build directed (type) relations between bind targets as they must appear in
    the REAL graph:
      - direct structural bind-target -> bind-target edges
      - operational relations recovered from marker chains
        (A ->S-> m, m ->S-> B, m op self-loop)  ==>  A ->OP-> B
    Returns dict: src -> list[(tgt, edge_type)].
    """
    markers = {n for n in input_graph.nodes
               if Edge(n, n, EdgeType.OPERATIONAL) in input_graph
               and Edge(n, n, EdgeType.STRUCTURAL) not in input_graph}
    bt = view.bind_targets
    rel: dict[Node, list[tuple[Node, EdgeType]]] = {n: [] for n in bt}

    # Direct structural edges between bind targets
    for e in input_graph.edges:
        if e.edge_type == EdgeType.STRUCTURAL and e.source != e.target:
            if e.source in bt and e.target in bt:
                rel[e.source].append((e.target, EdgeType.STRUCTURAL))

    # Operational relations via marker chains
    for m in markers:
        preds = [e.source for e in input_graph.edges_to(m, EdgeType.STRUCTURAL)
                 if e.source != m and e.source in bt]
        succs = [e.target for e in input_graph.edges_from(m, EdgeType.STRUCTURAL)
                 if e.target != m and e.target in bt]
        for s in preds:
            for t in succs:
                rel[s].append((t, EdgeType.OPERATIONAL))
    return rel


def match_cut_at_edge(
    input_graph: PerspectiveGraph,
    graph: PerspectiveGraph,
    candidates: list[Node],
    view: MatchView | None = None,
    seed_map: dict[Node, Node] | None = None,
) -> dict[Node, Node] | None:
    """
    Find a binding of the view's bind targets to real nodes in `candidates` such
    that (a) internal relations hold in the real graph and (b) each real node's
    TOTAL degree equals the bind target's derived expected degree.

    seed_map: optional pre-established partial mapping (bind_target -> real_node).
        Seeded nodes are accepted as-is and skipped in the search.
        Allows dispatch to pass the accumulated core correspondence directly,
        so backtracking only covers the delta nodes not yet matched.

    Returns one node_map (bind target -> real node) or None.
    """
    if view is None:
        view = derive_match_view(input_graph)

    targets = list(view.bind_targets)
    rel = _input_relations(input_graph, view)

    # Candidate pre-filter by degree (the cut). Only nodes whose total degree
    # equals the target's expected degree are viable.
    cand_for: dict[Node, list[Node]] = {}
    for t in targets:
        if seed_map and t in seed_map:
            cand_for[t] = [seed_map[t]]  # seed fixes this target
            continue
        exp = view.expected_degree[t]
        cand_for[t] = [g for g in candidates
                       if real_total_degree(g, graph) == exp]
        if not cand_for[t]:
            return None

    # Seeded targets first (zero search cost), then unseen targets by candidate count
    seeded = [t for t in targets if seed_map and t in seed_map]
    unseeded = sorted(
        [t for t in targets if not (seed_map and t in seed_map)],
        key=lambda t: len(cand_for[t])
    )
    order = seeded + unseeded

    def consistent(t: Node, g: Node, mapping: dict, reverse: dict) -> bool:
        if g in reverse:
            return False
        # outgoing relations from t whose target is already mapped
        for (t_nbr, etype) in rel[t]:
            if t_nbr in mapping:
                if Edge(g, mapping[t_nbr], etype) not in graph:
                    return False
        # incoming relations into t (find relations pointing at t)
        for src, lst in rel.items():
            if src in mapping:
                for (t_nbr, etype) in lst:
                    if t_nbr == t:
                        if Edge(mapping[src], g, etype) not in graph:
                            return False
        return True

    result: dict[Node, Node] = {}

    def crossing_ok(mapping: dict) -> bool:
        """Full-binding check: each bound node's CROSSING degree (edges leaving the
        matched region) must equal the bind target's declared expected_crossing.
        Internal relations are already confirmed by consistent(); this restores the
        internal/crossing SPLIT the total-degree cut discards, so a node cannot
        satisfy an expected-internal slot with an edge that leaves the region."""
        region = set(mapping.values())
        for t, g in mapping.items():
            exp_cross = view.expected_crossing.get(t, {})
            real_cross: dict[DegreeKey, int] = {}
            if Edge(g, g, EdgeType.STRUCTURAL) in graph:
                pass  # self-loop is internal, never crossing
            for e in graph.edges_from(g):
                if e.source == e.target:
                    continue
                if e.target not in region:
                    k = (e.edge_type, 'out')
                    real_cross[k] = real_cross.get(k, 0) + 1
            for e in graph.edges_to(g):
                if e.source == e.target:
                    continue
                if e.source not in region:
                    k = (e.edge_type, 'in')
                    real_cross[k] = real_cross.get(k, 0) + 1
            if real_cross != exp_cross:
                return False
        return True

    def backtrack(depth: int, mapping: dict, reverse: dict) -> bool:
        if depth == len(order):
            if not crossing_ok(mapping):
                return False
            result.update(mapping)
            return True
        t = order[depth]
        for g in cand_for[t]:
            if consistent(t, g, mapping, reverse):
                mapping[t] = g
                reverse[g] = t
                if backtrack(depth + 1, mapping, reverse):
                    return True
                del mapping[t]
                del reverse[g]
        return False

    if backtrack(0, {}, {}):
        return result
    return None
