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


def _mapping_is_valid(
    mapping: dict[Node, Node],
    pattern: PerspectiveGraph,
    graph: PerspectiveGraph
) -> bool:
    for edge in pattern.edges:
        mapped_source = mapping[edge.source]
        mapped_target = mapping[edge.target]
        expected = Edge(source=mapped_source, target=mapped_target, edge_type=edge.edge_type)
        if expected not in graph:
            return False
    return True


def match(
    pattern: PerspectiveGraph,
    graph: PerspectiveGraph,
) -> MatchResult:
    pattern_nodes = list(pattern.nodes)
    graph_nodes = list(graph.nodes)
    if len(pattern_nodes) > len(graph_nodes):
        return MatchResult(success=False)
    for mapping in _candidate_mappings(pattern_nodes, graph_nodes):
        if _mapping_is_valid(mapping, pattern, graph):
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


def _build_retyped_subgraph(
    source: PerspectiveGraph,
    nodes: set[Node],
    strip_type: EdgeType,
) -> PerspectiveGraph:
    """Build a subgraph of source restricted to nodes, excluding strip_type edges.
    Used to build the input subgraph for matching — only structural context,
    no mapping edges."""
    g = PerspectiveGraph()
    g._nodes = set(nodes)
    g._next_id = source._next_id
    for edge in source.edges:
        if edge.source in nodes and edge.target in nodes:
            if edge.edge_type != strip_type:
                g._edges.add(Edge(
                    source=edge.source,
                    target=edge.target,
                    edge_type=edge.edge_type,
                ))
    return g


def _apply_pass(
    graph: PerspectiveGraph,
    node_map: dict[Node, Node],
    transition: PerspectiveGraph,
    strip_type: EdgeType,
) -> dict[Node, Node]:
    output_type = (
        EdgeType.OPERATIONAL
        if strip_type == EdgeType.STRUCTURAL
        else EdgeType.STRUCTURAL
    )
    matched_target_nodes = set(node_map.values())

    # Step 1: convert strip_type edges to output_type in matched subgraph.
    # Recorded for reattachment. Converting instead of removing preserves
    # structural context so input subgraph matching is unambiguous.
    stripped_edges = []
    for edge in list(graph.edges):
        if (
            edge.edge_type == strip_type
            and edge.source in matched_target_nodes
            and edge.target in matched_target_nodes
        ):
            stripped_edges.append(edge)
            graph.remove_edge(edge)
            graph.add_edge(edge.source, edge.target, output_type)

    # Step 2: identify output-only nodes in transition.
    # Output-only = have incoming strip_type edges but no outgoing strip_type edges.
    # Input subgraph = all transition nodes except output-only nodes.
    has_outgoing: set[Node] = set()
    has_incoming: set[Node] = set()
    for edge in transition.edges:
        if edge.edge_type == strip_type:
            has_outgoing.add(edge.source)
            has_incoming.add(edge.target)
    output_only = has_incoming - has_outgoing
    input_nodes = set(transition.nodes) - output_only

    # Step 3: match input subgraph (strip_type retyped as output_type) against
    # matched subgraph (which also has strip_type converted to output_type).
    retyped_input = _build_retyped_subgraph(transition, input_nodes, strip_type)
    matched_subgraph = graph.subgraph(matched_target_nodes)
    input_match = match(retyped_input, matched_subgraph)
    with open('debug_out.txt', 'a') as f:
        f.write(f"strip={strip_type} input_nodes={len(input_nodes)} retyped_input nodes={len(list(retyped_input.nodes))} edges={len(list(retyped_input.edges))} matched_subgraph nodes={len(list(matched_subgraph.nodes))} edges={len(list(matched_subgraph.edges))} match={input_match.success} map={input_match.node_map}\n")
    if not input_match.success:
        # Revert conversion
        for edge in stripped_edges:
            temp = Edge(source=edge.source, target=edge.target, edge_type=output_type)
            if temp in graph:
                graph.remove_edge(temp)
            graph.add_edge(edge.source, edge.target, strip_type)
        return node_map

    # Step 4: follow strip_type edges to build output_node_map
    output_node_map: dict[Node, Node] = {}
    visited: set[Node] = set()

    def follow_mapping(t_node: Node, target: Node) -> None:
        if t_node in visited:
            return
        visited.add(t_node)
        output_node_map[t_node] = target
        for edge in transition.edges_from(t_node, strip_type):
            if edge.target not in output_node_map:
                if edge.target in input_match.node_map:
                    follow_mapping(edge.target, input_match.node_map[edge.target])
                else:
                    follow_mapping(edge.target, graph.add_node())

    for t_input, target in input_match.node_map.items():
        if t_input in has_outgoing:
            follow_mapping(t_input, target)

    # Step 4b: remove unmapped nodes from target graph
    for target_node in matched_target_nodes:
        if target_node not in output_node_map.values():
            for edge in list(graph.edges):
                if edge.source == target_node or edge.target == target_node:
                    graph.remove_edge(edge)
            graph.remove_node(target_node)

    # Step 5: write output_type edges from transition into target graph
    for edge in transition.edges:
        if edge.edge_type != output_type:
            continue
        source = output_node_map.get(edge.source)
        target = output_node_map.get(edge.target)
        if source is not None and target is not None:
            candidate = Edge(source=source, target=target, edge_type=output_type)
            if candidate not in graph:
                graph.add_edge(source, target, output_type)

    # Step 6: reattach as strip_type where both endpoints survived.
    # Remove temporary output_type conversion and restore as strip_type.
    for edge in stripped_edges:
        new_source = output_node_map.get(edge.source)
        new_target = output_node_map.get(edge.target)
        if new_source is not None and new_target is not None:
            temp = Edge(source=new_source, target=new_target, edge_type=output_type)
            if temp in graph:
                graph.remove_edge(temp)
            graph.add_edge(new_source, new_target, strip_type)

    return output_node_map


def apply(
    graph: PerspectiveGraph,
    operation: OperationDefinition,
) -> bool:
    result = match(operation.pattern, graph)
    if not result.success:
        return False

    # Pass 1: convert operational to structural, output structural — fires graph2s
    updated_map = _apply_pass(
        graph,
        result.node_map,
        operation.graph2s,
        strip_type=EdgeType.OPERATIONAL,
    )

    # Pass 2: convert structural to operational, output operational — fires graph2o
    _apply_pass(
        graph,
        updated_map,
        operation.graph2o,
        strip_type=EdgeType.STRUCTURAL,
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
