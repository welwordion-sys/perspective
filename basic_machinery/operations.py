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
    graph2s: PerspectiveGraph
    graph2o: PerspectiveGraph


_registry: dict[str, OperationDefinition] = {}


def register(operation: OperationDefinition) -> None:
    if operation.name in _registry:
        raise ValueError(f"Operation '{operation.name}' is already registered.")
    _registry[operation.name] = operation


def lookup(name: str) -> OperationDefinition:
    if name not in _registry:
        raise KeyError(f"No operation registered under '{name}'.")
    return _registry[name]


def _candidate_mappings(
    pattern_nodes: list[Node],
    graph_nodes: list[Node]
) -> Iterator[dict[Node, Node]]:
    from itertools import permutations
    for perm in permutations(graph_nodes, len(pattern_nodes)):
        yield dict(zip(pattern_nodes, perm))


def _is_placeholder(node: Node, graph: PerspectiveGraph) -> bool:
    """
    A placeholder node has both a structural self-loop and an operational self-loop.
    Unique signature in the system — used to represent external boundary connections
    in transition input subgraphs. Never appears in the real graph.
    """
    has_s = Edge(source=node, target=node, edge_type=EdgeType.STRUCTURAL) in graph
    has_o = Edge(source=node, target=node, edge_type=EdgeType.OPERATIONAL) in graph
    return has_s and has_o


def _mapping_is_valid(
    mapping: dict[Node, Node],
    pattern: PerspectiveGraph,
    graph: PerspectiveGraph,
    exact: bool = False,
    real_candidates: set[Node] | None = None,
) -> bool:
    """
    Check if mapping is a valid (sub)graph isomorphism from pattern into graph.

    exact=True: each mapped real node must have exactly the same outgoing edge
    count per type as its pattern counterpart, excluding edges to real nodes
    outside real_candidates (those are external edges, matched via placeholder).

    Placeholder nodes in the pattern (structural+operational self-loop) are
    wildcard boundary nodes — they can match any real node outside real_candidates.
    The match only checks that the edge from the boundary node to the placeholder
    exists in the real graph as an external edge (target outside real_candidates).
    """
    for edge in pattern.edges:
        mapped_source = mapping[edge.source]
        mapped_target = mapping[edge.target]
        expected = Edge(source=mapped_source, target=mapped_target, edge_type=edge.edge_type)
        if expected not in graph:
            return False
    if exact and real_candidates is not None:
        reverse_mapping = {v: k for k, v in mapping.items()}
        for real_node, pattern_node in reverse_mapping.items():
            if real_node not in real_candidates:
                continue  # placeholder or external node — skip count check
            for edge_type in (EdgeType.STRUCTURAL, EdgeType.OPERATIONAL):
                # Count real edges excluding those going to external nodes
                real_edges = [
                    e for e in graph.edges_from(real_node, edge_type)
                    if e.target in real_candidates or e.target == real_node
                ]
                pattern_edges = list(pattern.edges_from(pattern_node, edge_type))
                if len(real_edges) != len(pattern_edges):
                    return False
    return True


def match(
    pattern: PerspectiveGraph,
    graph: PerspectiveGraph,
    candidates: list[Node] | None = None,
    exact: bool = False,
    real_candidates: set[Node] | None = None,
) -> MatchResult:
    pattern_nodes = list(pattern.nodes)
    graph_nodes = candidates if candidates is not None else list(graph.nodes)
    if len(pattern_nodes) > len(graph_nodes):
        return MatchResult(success=False)
    for mapping in _candidate_mappings(pattern_nodes, graph_nodes):
        if _mapping_is_valid(mapping, pattern, graph, exact=exact, real_candidates=real_candidates):
            return MatchResult(success=True, node_map=mapping)
    return MatchResult(success=False)


def match_all(
    pattern: PerspectiveGraph,
    graph: PerspectiveGraph,
) -> list[MatchResult]:
    pattern_nodes = list(pattern.nodes)
    graph_nodes = list(graph.nodes)
    results = []
    for mapping in _candidate_mappings(pattern_nodes, graph_nodes):
        if _mapping_is_valid(mapping, pattern, graph):
            results.append(MatchResult(success=True, node_map=dict(mapping)))
    return results


def snapshot(graph: PerspectiveGraph) -> PerspectiveGraph:
    return graph.copy()


def revert(graph: PerspectiveGraph, snap: PerspectiveGraph) -> None:
    graph.restore(snap)


def _apply_pass(
    graph: PerspectiveGraph,
    node_map: dict[Node, Node],
    transition: PerspectiveGraph,
) -> dict[Node, Node]:
    """
    Apply one transformation pass using the transition graph.

    The transition graph encodes:
      - Input side: mirrors the real matched subgraph topology, with operational
        edges represented as marker chains (A->[S]->m->[S]->B, m->[OP]->m),
        and boundary nodes connected to a shared placeholder (structural+operational
        self-loop) representing external connections.
      - Output side: describes the desired final state of surviving nodes.
        STRUCTURAL edges written as STRUCTURAL. Marker chains written as OPERATIONAL.
      - OPERATIONAL non-self-loop edges: input->output mapping instructions.

    Steps:
      1. Insert marker nodes for operational edges in real matched subgraph.
      2. Classify transition nodes (input vs output, excluding transition markers
         and the placeholder).
      3. Exact-match transition input subgraph against real graph.
         Candidate pool = matched_target_nodes | marker_nodes.
         Placeholder nodes in transition match real external nodes (outside candidates).
         Exact count check excludes edges to external nodes (matched via placeholder).
      4. Follow OPERATIONAL edges in transition to build output_map.
         Collect nodes_to_delete and nodes_to_merge.
      4b. Delete merged nodes, delete unconsumed nodes, remove marker nodes.
      5. Write edges from transition output side into real graph.
         Plain STRUCTURAL edges -> STRUCTURAL.
         Marker chains -> OPERATIONAL.
    """
    matched_target_nodes = set(node_map.values())

    # ------------------------------------------------------------------
    # Step 1: Insert marker nodes for OPERATIONAL edges in matched subgraph.
    # A->[OP]->B becomes A->[S]->m, m->[S]->B, m->[OP]->m
    # Self-loops left unchanged.
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
    # Exclude transition markers (operational self-loop only) and
    # placeholder nodes (both self-loops) from classification.
    # ------------------------------------------------------------------
    transition_markers: set[Node] = set()
    transition_placeholders: set[Node] = set()
    for n in transition.nodes:
        has_s = Edge(source=n, target=n, edge_type=EdgeType.STRUCTURAL) in transition
        has_o = Edge(source=n, target=n, edge_type=EdgeType.OPERATIONAL) in transition
        if has_s and has_o:
            transition_placeholders.add(n)
        elif has_o:
            transition_markers.add(n)

    has_outgoing: set[Node] = set()
    has_incoming: set[Node] = set()
    for edge in transition.edges:
        if edge.edge_type == EdgeType.OPERATIONAL and edge.source != edge.target:
            has_outgoing.add(edge.source)
            has_incoming.add(edge.target)
    output_only = has_incoming - has_outgoing
    excluded = transition_markers | transition_placeholders
    input_nodes = set(transition.nodes) - output_only - excluded

    # ------------------------------------------------------------------
    # Step 3: Exact-match transition input subgraph against real graph.
    # Candidates = matched_target_nodes | marker_nodes (not placeholder targets).
    # Placeholder nodes in transition can match any real node outside candidates.
    # Exact count excludes edges to external nodes.
    # ------------------------------------------------------------------
    # Include placeholder nodes in input_subgraph so edge counts to placeholder
    # are visible during matching.
    input_subgraph = transition.subgraph(input_nodes | transition_markers | transition_placeholders)
    all_candidates = list(matched_target_nodes | marker_nodes) + list(graph.nodes - matched_target_nodes - marker_nodes)
    real_candidates = matched_target_nodes | marker_nodes

    input_match = match(
        input_subgraph,
        graph,
        candidates=all_candidates,
        exact=True,
        real_candidates=real_candidates,
    )

    if not input_match.success:
        # Revert step 1: restore original operational edges, remove markers
        for m in list(marker_nodes):
            incoming = [e for e in graph.edges if e.target == m and e.source != m]
            outgoing = [e for e in graph.edges if e.source == m and e.target != m]
            for edge in list(graph.edges):
                if edge.source == m or edge.target == m:
                    graph.remove_edge(edge)
            if incoming and outgoing:
                graph.add_edge(incoming[0].source, outgoing[0].target, EdgeType.OPERATIONAL)
            graph.remove_node(m)
        return node_map

    # ------------------------------------------------------------------
    # Step 4: Follow OPERATIONAL edges in transition to build output_map.
    # Only process input nodes that are in real_candidates (not placeholder/external).
    # output_map: transition output node -> real node
    # nodes_to_delete: input nodes with no output (consumed)
    # nodes_to_merge: real node -> survivor
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
            continue  # placeholder assignment — skip, not a real matched node
        if t_input in has_outgoing:
            follow_mapping(t_input, real)
        else:
            nodes_to_delete.add(real)

    # ------------------------------------------------------------------
    # Step 4b: Merge, delete, clean up markers.
    # ------------------------------------------------------------------

    # Merge: rewrite edges to survivor, remove merged node
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

    # Delete: remove all edges then remove node
    for real_node in nodes_to_delete:
        if real_node not in graph:
            continue
        for edge in list(graph.edges):
            if edge.source == real_node or edge.target == real_node:
                graph.remove_edge(edge)
        graph.remove_node(real_node)

    # Remove marker nodes (always temporary)
    for m in marker_nodes:
        if m not in graph:
            continue
        for edge in list(graph.edges):
            if edge.source == m or edge.target == m:
                graph.remove_edge(edge)
        graph.remove_node(m)

    # ------------------------------------------------------------------
    # Step 5: Write edges from transition output side into real graph.
    # Plain STRUCTURAL edges -> STRUCTURAL.
    # Marker chains (A->[S]->m->[S]->B, m->[OP]->m) -> OPERATIONAL.
    # ------------------------------------------------------------------
    for t_marker in transition_markers:
        incoming = [
            e for e in transition.edges
            if e.target == t_marker
            and e.source != t_marker
            and e.edge_type == EdgeType.STRUCTURAL
        ]
        outgoing = [
            e for e in transition.edges
            if e.source == t_marker
            and e.target != t_marker
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
            continue  # placeholder edges are matching artifacts, not real output
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
    result = match(operation.pattern, graph)
    if not result.success:
        return False

    # Pass 1: graph2s — structural rewrite
    updated_map = _apply_pass(
        graph,
        result.node_map,
        operation.graph2s,
    )

    # Pass 2: graph2o — operational rewrite
    _apply_pass(
        graph,
        updated_map,
        operation.graph2o,
    )

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
