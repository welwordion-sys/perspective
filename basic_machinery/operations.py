from __future__ import annotations
from dataclasses import dataclass, field
from typing import Iterator
from basic_machinery.graph import PerspectiveGraph, Node, Edge, EdgeType


@dataclass
class MatchResult:
    success: bool
    node_map: dict[Node, Node] = field(default_factory=dict)


@dataclass
class OperationDefinition:
    name: str
    pattern: PerspectiveGraph
    graph2: PerspectiveGraph


_registry: dict[str, OperationDefinition] = {}


def register(operation: OperationDefinition) -> None:
    if operation.name in _registry:
        raise ValueError(f"Operation '{operation.name}' is already registered.")
    _registry[operation.name] = operation


def lookup(name: str) -> OperationDefinition:
    if name not in _registry:
        raise KeyError(f"No operation registered under '{name}'.")
    return _registry[name]


# ---------------------------------------------------------------------------
# Node fingerprint for VF2 candidate filtering
# ---------------------------------------------------------------------------

def _node_fingerprint(node: Node, graph: PerspectiveGraph) -> tuple:
    s_out  = sum(1 for e in graph.edges_from(node, EdgeType.STRUCTURAL)  if e.target != node)
    s_in   = sum(1 for e in graph.edges_to(node,   EdgeType.STRUCTURAL)  if e.source != node)
    s_self = 1 if Edge(source=node, target=node, edge_type=EdgeType.STRUCTURAL)  in graph else 0
    o_out  = sum(1 for e in graph.edges_from(node, EdgeType.OPERATIONAL) if e.target != node)
    o_in   = sum(1 for e in graph.edges_to(node,   EdgeType.OPERATIONAL) if e.source != node)
    o_self = 1 if Edge(source=node, target=node, edge_type=EdgeType.OPERATIONAL) in graph else 0
    return (s_out, s_in, s_self, o_out, o_in, o_self)


def _fingerprint_compatible(p_fp: tuple, g_fp: tuple, exact: bool) -> bool:
    if exact:
        return p_fp == g_fp
    for i in range(6):
        if i in (2, 5):  # self-loops must match exactly
            if p_fp[i] != g_fp[i]:
                return False
        else:
            if g_fp[i] < p_fp[i]:
                return False
    return True


# ---------------------------------------------------------------------------
# VF2 subgraph isomorphism
# ---------------------------------------------------------------------------

def _vf2_match(
    pattern: PerspectiveGraph,
    graph: PerspectiveGraph,
    candidates: list[Node] | None = None,
    exact: bool = False,
    real_candidates: set[Node] | None = None,
    find_all: bool = False,
) -> list[dict[Node, Node]]:
    pattern_nodes = list(pattern.nodes)
    graph_nodes = candidates if candidates is not None else list(graph.nodes)

    if len(pattern_nodes) > len(graph_nodes):
        return []

    graph_fps = {n: _node_fingerprint(n, graph) for n in graph_nodes}
    pattern_fps = {n: _node_fingerprint(n, pattern) for n in pattern_nodes}

    initial_candidates: dict[Node, list[Node]] = {}
    for pn in pattern_nodes:
        p_fp = pattern_fps[pn]
        initial_candidates[pn] = [
            gn for gn in graph_nodes
            if _fingerprint_compatible(p_fp, graph_fps[gn], exact)
        ]

    # Order by fewest candidates first (most constrained)
    order = sorted(pattern_nodes, key=lambda n: len(initial_candidates[n]))

    pat_edges_from: dict[Node, list[tuple[Node, EdgeType]]] = {n: [] for n in pattern_nodes}
    pat_edges_to:   dict[Node, list[tuple[Node, EdgeType]]] = {n: [] for n in pattern_nodes}
    for e in pattern.edges:
        pat_edges_from[e.source].append((e.target, e.edge_type))
        pat_edges_to[e.target].append((e.source, e.edge_type))

    results: list[dict[Node, Node]] = []

    def _consistent(pn: Node, gn: Node, mapping: dict[Node, Node], reverse: dict[Node, Node]) -> bool:
        if gn in reverse:
            return False
        for (pn_nbr, etype) in pat_edges_from[pn]:
            if pn_nbr in mapping:
                if Edge(source=gn, target=mapping[pn_nbr], edge_type=etype) not in graph:
                    return False
        for (pn_src, etype) in pat_edges_to[pn]:
            if pn_src in mapping:
                if Edge(source=mapping[pn_src], target=gn, edge_type=etype) not in graph:
                    return False
        return True

    def _exact_count_ok(pn: Node, gn: Node) -> bool:
        if not exact or real_candidates is None:
            return True
        if gn not in real_candidates:
            return True
        for edge_type in (EdgeType.STRUCTURAL, EdgeType.OPERATIONAL):
            real_edges = [
                e for e in graph.edges_from(gn, edge_type)
                if e.target in real_candidates or e.target == gn
            ]
            if len(real_edges) != len(list(pattern.edges_from(pn, edge_type))):
                return False
        return True

    def _backtrack(depth: int, mapping: dict[Node, Node], reverse: dict[Node, Node]) -> None:
        if depth == len(order):
            results.append(dict(mapping))
            return
        pn = order[depth]
        for gn in initial_candidates[pn]:
            if _consistent(pn, gn, mapping, reverse) and _exact_count_ok(pn, gn):
                mapping[pn] = gn
                reverse[gn] = pn
                _backtrack(depth + 1, mapping, reverse)
                del mapping[pn]
                del reverse[gn]
                if results and not find_all:
                    return

    _backtrack(0, {}, {})
    return results


# ---------------------------------------------------------------------------
# Public match interface
# ---------------------------------------------------------------------------

def _is_placeholder(node: Node, graph: PerspectiveGraph) -> bool:
    has_s = Edge(source=node, target=node, edge_type=EdgeType.STRUCTURAL)  in graph
    has_o = Edge(source=node, target=node, edge_type=EdgeType.OPERATIONAL) in graph
    return has_s and has_o


def match(
    pattern: PerspectiveGraph,
    graph: PerspectiveGraph,
    candidates: list[Node] | None = None,
    exact: bool = False,
    real_candidates: set[Node] | None = None,
) -> MatchResult:
    results = _vf2_match(pattern, graph, candidates=candidates, exact=exact,
                         real_candidates=real_candidates, find_all=False)
    if results:
        return MatchResult(success=True, node_map=results[0])
    return MatchResult(success=False)


def match_all(
    pattern: PerspectiveGraph,
    graph: PerspectiveGraph,
) -> list[MatchResult]:
    results = _vf2_match(pattern, graph, find_all=True)
    return [MatchResult(success=True, node_map=m) for m in results]


def snapshot(graph: PerspectiveGraph) -> PerspectiveGraph:
    return graph.copy()


def revert(graph: PerspectiveGraph, snap: PerspectiveGraph) -> None:
    graph.restore(snap)


# ---------------------------------------------------------------------------
# _apply_pass — single unified pass
# ---------------------------------------------------------------------------

def _apply_pass(
    graph: PerspectiveGraph,
    node_map: dict[Node, Node],
    transition: PerspectiveGraph,
) -> dict[Node, Node]:
    """
    Apply one transformation pass using the unified transition graph.

    node_map is the FIRING BINDING produced by the cut-at-edge match in apply()
    (bind_target -> real_node, keyed by input-side transition nodes). It is the
    single source of correspondence: the same binding that decided the rule fires
    drives the rewrite. There is no separate step-3 re-match.

    Why step 3 is gone: in the old two-pass scheme the matched input nodes were a
    SUBGRAPH of the matching, so a reconciliation match (step 3) was needed to
    re-establish correspondence between the input-node set and the real region.
    With the derived match view, the bind targets ARE the matched set exactly, so
    the firing binding already spans the rewrite. No reconciliation remains.

    The transition graph stays the single representation: input->output mapping
    and output structure are read LIVE from `transition` here (steps 4-5), never
    cached, because `transition` is the medium the GA mutates.

    Steps:
      1. Insert marker nodes for OPERATIONAL edges in matched subgraph.
      2. Classify transition nodes (markers, placeholders, input, output) — needed
         by steps 4-5; read live from the transition graph.
      4. Follow OPERATIONAL input->output edges to build output_map, seeded by the
         firing binding.
      4b. Merge, delete, remove markers.
      5. Write output edges (STRUCTURAL direct, OPERATIONAL via marker chains).
    """
    matched_target_nodes = set(node_map.values())


    # ------------------------------------------------------------------
    # Step 1: Insert marker nodes for OPERATIONAL edges in matched subgraph.
    # ------------------------------------------------------------------
    marker_nodes: set[Node] = set()
    for edge in list(graph.edges):
        if (
            edge.edge_type == EdgeType.OPERATIONAL
            and edge.source != edge.target
            and edge.source in matched_target_nodes
            and edge.target in matched_target_nodes
        ):
            graph.remove_edge(edge)
            m = graph.add_node()
            marker_nodes.add(m)
            graph.add_edge(edge.source, m, EdgeType.STRUCTURAL)
            graph.add_edge(m, edge.target, EdgeType.STRUCTURAL)
            graph.add_edge(m, m, EdgeType.OPERATIONAL)

    # ------------------------------------------------------------------
    # Step 2: Classify transition nodes.
    # ------------------------------------------------------------------
    transition_all_markers: set[Node] = set()
    transition_placeholders: set[Node] = set()
    for n in transition.nodes:
        has_s = Edge(source=n, target=n, edge_type=EdgeType.STRUCTURAL)  in transition
        has_o = Edge(source=n, target=n, edge_type=EdgeType.OPERATIONAL) in transition
        if has_s and has_o:
            transition_placeholders.add(n)
        elif has_o:
            transition_all_markers.add(n)

    has_outgoing: set[Node] = set()
    has_incoming: set[Node] = set()
    for edge in transition.edges:
        if edge.edge_type == EdgeType.OPERATIONAL and edge.source != edge.target:
            has_outgoing.add(edge.source)
            has_incoming.add(edge.target)
    output_only = has_incoming - has_outgoing
    excluded = transition_all_markers | transition_placeholders
    input_nodes = set(transition.nodes) - output_only - excluded

    # Split markers into input-side (structural neighbours in input_nodes) and
    # output-side (structural neighbours all in output_only). Only input-side
    # markers appear in the step 3 match; output-side markers are used in step 5.
    transition_input_markers: set[Node] = set()
    transition_output_markers: set[Node] = set()
    for m in transition_all_markers:
        s_neighbours = set(
            e.source if e.target == m else e.target
            for e in transition.edges
            if (e.source == m or e.target == m)
            and e.source != e.target
            and e.edge_type == EdgeType.STRUCTURAL
        )
        if s_neighbours & input_nodes:
            transition_input_markers.add(m)
        else:
            transition_output_markers.add(m)

    # For step 5 we need all markers (both input and output side)
    transition_markers = transition_all_markers

    # ------------------------------------------------------------------
    # Step 3 REMOVED. The firing binding (node_map) is the correspondence.
    # We adopt it directly; real_candidates is the matched real region plus
    # the markers step 1 just inserted (needed by step 4's reuse logic).
    # ------------------------------------------------------------------
    real_candidates = matched_target_nodes | marker_nodes
    input_match = MatchResult(success=True, node_map=dict(node_map))

    # ------------------------------------------------------------------
    # Step 4: Build output_map from OPERATIONAL input->output edges.
    # ------------------------------------------------------------------
    output_map: dict[Node, Node] = {}
    nodes_to_delete: set[Node] = set()
    nodes_to_merge: dict[Node, Node] = {}

    def follow_mapping(t_input: Node, real: Node) -> None:
        current_real = real
        edges_from = [
            e for e in transition.edges_from(t_input, EdgeType.OPERATIONAL)
            if e.target != t_input
        ]
        for i, edge in enumerate(edges_from):
            t_out = edge.target
            if t_out not in output_map:
                output_map[t_out] = current_real
                if i < len(edges_from) - 1:
                    current_real = graph.add_node()
            else:
                existing_real = output_map[t_out]
                if current_real != existing_real:
                    nodes_to_merge[current_real] = existing_real

    for t_input, real in input_match.node_map.items():
        if real not in real_candidates:
            continue
        if t_input in has_outgoing:
            follow_mapping(t_input, real)
        else:
            nodes_to_delete.add(real)

    # ------------------------------------------------------------------
    # Step 4b: Merge, delete, clean up markers. Recycle deleted/marker
    # nodes as fresh nodes for output-only transition nodes.
    #
    # Output-only nodes not yet in output_map are fresh nodes — they
    # draw from the recycle pool before creating new ones.
    # Output-only nodes connected to a placeholder in the transition
    # preserve external edges (future use — currently unused).
    # ------------------------------------------------------------------

    def _strip_node_save_external(real_node: Node) -> list[Edge]:
        """Strip all edges from real_node, return external edges for possible restore."""
        external = [
            e for e in graph.edges
            if (e.source == real_node or e.target == real_node)
            and e.source not in real_candidates
            and e.target not in real_candidates
        ]
        # Actually we want edges where ONE endpoint is real_node and the
        # other is outside real_candidates
        external = [
            e for e in graph.edges
            if (e.source == real_node and e.target not in real_candidates)
            or (e.target == real_node and e.source not in real_candidates)
        ]
        for edge in list(graph.edges):
            if edge.source == real_node or edge.target == real_node:
                graph.remove_edge(edge)
        return external

    # Merge
    for real_node, survivor in nodes_to_merge.items():
        for edge in list(graph.edges):
            if edge.source == real_node or edge.target == real_node:
                graph.remove_edge(edge)
                new_src = survivor if edge.source == real_node else edge.source
                new_tgt = survivor if edge.target == real_node else edge.target
                candidate = Edge(source=new_src, target=new_tgt, edge_type=edge.edge_type)
                if candidate not in graph:
                    graph.add_edge(new_src, new_tgt, edge.edge_type)
        if real_node in graph:
            graph.remove_node(real_node)

    # Strip deleted nodes into recycle pool, saving external edges per node
    recycle_pool: list[tuple[Node, list[Edge]]] = []
    for real_node in nodes_to_delete:
        if real_node not in graph:
            continue
        external = _strip_node_save_external(real_node)
        recycle_pool.append((real_node, external))

    # Strip marker nodes into recycle pool
    for m in marker_nodes:
        if m not in graph:
            continue
        external = _strip_node_save_external(m)
        recycle_pool.append((m, external))

    # Assign real nodes to all output-side transition nodes not yet in output_map.
    # Output nodes are all transition nodes that were NOT part of the step 3
    # input match — i.e. not in input_match.node_map — and are not markers or
    # placeholders. This correctly excludes consumed input nodes (e.g. bit nodes
    # with no outgoing OPERATIONAL edge) from being treated as output nodes.
    all_output_nodes = set(transition.nodes) - input_nodes - transition_all_markers - transition_placeholders
    for t_out in all_output_nodes:
        if t_out in output_map:
            continue

        has_placeholder_out = any(
            (e.source == t_out and e.target in transition_placeholders) or
            (e.target == t_out and e.source in transition_placeholders)
            for e in transition.edges
        )

        if recycle_pool:
            real_node, saved_external = recycle_pool.pop()
        else:
            real_node = graph.add_node()
            saved_external = []

        if has_placeholder_out:
            # Restore external edges from the recycled node's previous life
            for edge in saved_external:
                candidate = Edge(source=edge.source, target=edge.target, edge_type=edge.edge_type)
                if candidate not in graph:
                    graph.add_edge(edge.source, edge.target, edge.edge_type)

        output_map[t_out] = real_node

    # Any nodes still in the recycle pool were stripped of edges (on entry) but
    # never reused as output reals. Leaving them produces edge-less ORPHAN nodes
    # (the step-1 markers that outnumbered output demand; see KB
    # step1_markers_orphaned_on_success). Reuse is an optimisation; removing the
    # leftovers is the correctness requirement — an unconsumed stripped node must
    # not survive the rewrite.
    for leftover_node, _saved in recycle_pool:
        if leftover_node in graph:
            graph.remove_node(leftover_node)
    recycle_pool.clear()

    # ------------------------------------------------------------------
    # Step 4c: Strip stale structural edges from surviving nodes — DIRECTION-SYMMETRIC.
    # (KB apply_pass_4c_directional_cleanup) The old 4c only iterated edges whose
    # SOURCE survived, so it governed a surviving node's OUTGOING external edges but
    # never its INCOMING ones (preserved by omission). That contradicts cut-at-edge
    # matching (degree counted per (type,direction)) and blocks add_finalise, which
    # must REDIRECT/strip the parent->operator INCOMING crossing when it consumes the
    # operator. Now: examine external edges in BOTH directions, governed by directional
    # placeholder records preserve_out / preserve_in.
    # ------------------------------------------------------------------

    desired_structural: set[tuple] = set()
    for edge in transition.edges:
        if edge.edge_type != EdgeType.STRUCTURAL:
            continue
        if edge.source in transition_all_markers or edge.target in transition_all_markers:
            continue
        if edge.source in transition_placeholders or edge.target in transition_placeholders:
            continue
        src_real = output_map.get(edge.source)
        tgt_real = output_map.get(edge.target)
        if src_real is not None and tgt_real is not None:
            desired_structural.add((src_real, tgt_real))

    # Directional placeholder records. A surviving output node connected to a
    # placeholder preserves its external edges — but only in the direction(s) the
    # placeholder edge runs:
    #   out_node -S-> placeholder   => preserve OUTGOING external edges (preserve_out)
    #   placeholder -S-> out_node   => preserve INCOMING external edges (preserve_in)
    # An undirected/legacy placeholder connection (either direction present) is
    # interpreted per its actual edge direction, so existing rules that only emit
    # out_node -> placeholder keep exactly their old (preserve_out) behaviour.
    preserve_out: set[Node] = set()
    preserve_in: set[Node] = set()
    for t_out, real_node in output_map.items():
        for e in transition.edges:
            if e.edge_type != EdgeType.STRUCTURAL:
                continue
            if e.source == t_out and e.target in transition_placeholders:
                preserve_out.add(real_node)
            if e.target == t_out and e.source in transition_placeholders:
                preserve_in.add(real_node)

    surviving_real = set(output_map.values())
    for edge in list(graph.edges):
        if edge.edge_type != EdgeType.STRUCTURAL:
            continue
        src_surv = edge.source in surviving_real
        tgt_surv = edge.target in surviving_real
        if not src_surv and not tgt_surv:
            continue  # edge entirely outside the rewrite — untouched
        if src_surv and tgt_surv:
            # internal edge — remove unless the transition output wants it
            if (edge.source, edge.target) not in desired_structural:
                graph.remove_edge(edge)
            continue
        # external edge with exactly one surviving endpoint
        if src_surv:
            # outgoing external edge from a surviving node
            if edge.source not in preserve_out:
                graph.remove_edge(edge)
        else:  # tgt_surv
            # incoming external edge into a surviving node
            if edge.target not in preserve_in:
                graph.remove_edge(edge)

    # ------------------------------------------------------------------
    # Step 5: Write output edges.
    # Marker chains in output side -> OPERATIONAL edges in real graph.
    # Plain STRUCTURAL edges in output side -> STRUCTURAL edges in real graph.
    # ------------------------------------------------------------------
    for t_marker in transition_markers:
        # Only process output-side markers (their source/target are output nodes)
        incoming = [
            e for e in transition.edges
            if e.target == t_marker and e.source != t_marker
            and e.edge_type == EdgeType.STRUCTURAL
        ]
        outgoing = [
            e for e in transition.edges
            if e.source == t_marker and e.target != t_marker
            and e.edge_type == EdgeType.STRUCTURAL
        ]
        for inc in incoming:
            for out in outgoing:
                src_real = output_map.get(inc.source)
                tgt_real = output_map.get(out.target)
                if src_real is not None and tgt_real is not None:
                    candidate = Edge(source=src_real, target=tgt_real, edge_type=EdgeType.OPERATIONAL)
                    if candidate not in graph:
                        graph.add_edge(src_real, tgt_real, EdgeType.OPERATIONAL)

    for edge in transition.edges:
        if edge.edge_type != EdgeType.STRUCTURAL:
            continue
        if edge.source in transition_markers or edge.target in transition_markers:
            continue
        if edge.source in transition_placeholders or edge.target in transition_placeholders:
            continue
        source = output_map.get(edge.source)
        target = output_map.get(edge.target)
        if source is None or target is None:
            continue
        candidate = Edge(source=source, target=target, edge_type=EdgeType.STRUCTURAL)
        if candidate not in graph:
            graph.add_edge(source, target, EdgeType.STRUCTURAL)

    return output_map


def apply(
    graph: PerspectiveGraph,
    operation: OperationDefinition,
) -> bool:
    # Firing decision: cut-at-edge match derived from the transition's input side
    # (operation.graph2), not a separate operation.pattern — the single
    # representation, so there is no second view to drift from under GA mutation.
    # Matching is on real TOTAL degree per (type, direction): the placeholders in
    # the input graph supply the expected crossing-edge component so a legitimate
    # boundary node's full degree balances. Runs in clean real-graph space, before
    # _apply_pass step 1 marker-encodes the matched region for the rewrite.
    from basic_machinery.match_view import derive_match_view, match_cut_at_edge
    view = derive_match_view(operation.graph2)
    node_map = match_cut_at_edge(
        operation.graph2, graph, list(graph.nodes), view=view
    )
    if node_map is None:
        return False
    _apply_pass(graph, node_map, operation.graph2)
    return True


def restore(
    graph: PerspectiveGraph,
    operation: OperationDefinition,
) -> bool:
    snap = snapshot(graph)
    success = apply(graph, operation)
    if not success:
        revert(graph, snap)
    return success
