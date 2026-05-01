from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Iterator
from basic_machinery.graph import PerspectiveGraph, Node, Edge, EdgeType


@dataclass
class MatchResult:
    success: bool
    node_map: dict[Node, Node] = field(default_factory=dict)


@dataclass
class OperationDefinition:
    name: str
    pattern: PerspectiveGraph
    rewrite: Callable[[PerspectiveGraph, MatchResult], None]


_registry: dict[str, OperationDefinition] = {}


def register(operation: OperationDefinition) -> None:
    if operation.name in _registry:
        raise ValueError(f"Operation '{operation.name}' is already registered.")
    _registry[operation.name] = operation


def lookup(name: str) -> OperationDefinition:
    if name not in _registry:
        raise KeyError(f"No operation registered under '{name}'.")
    return _registry[name]


def match(graph: PerspectiveGraph, pattern: PerspectiveGraph) -> MatchResult:
    pattern_nodes = list(pattern.nodes)
    graph_nodes = list(graph.nodes)

    if len(pattern_nodes) > len(graph_nodes):
        return MatchResult(success=False)

    for mapping in _candidate_mappings(pattern_nodes, graph_nodes):
        if _mapping_is_valid(mapping, pattern, graph):
            return MatchResult(success=True, node_map=mapping)

    return MatchResult(success=False)


def match_all(graph: PerspectiveGraph, pattern: PerspectiveGraph) -> list[MatchResult]:
    pattern_nodes = list(pattern.nodes)
    graph_nodes = list(graph.nodes)
    results = []

    for mapping in _candidate_mappings(pattern_nodes, graph_nodes):
        if _mapping_is_valid(mapping, pattern, graph):
            results.append(MatchResult(success=True, node_map=dict(mapping)))

    return results


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


def apply(
    graph: PerspectiveGraph,
    operation: OperationDefinition
) -> tuple[bool, PerspectiveGraph]:
    result = match(graph, operation.pattern)
    if not result.success:
        return False, graph
    operation.rewrite(graph, result)
    return True, graph


def snapshot(graph: PerspectiveGraph) -> PerspectiveGraph:
    return graph.copy()


def revert(graph: PerspectiveGraph, snap: PerspectiveGraph) -> PerspectiveGraph:
    graph.restore(snap)
    return graph