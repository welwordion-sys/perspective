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
        raise ValueError(
            f"Operation '{operation.name}' is already registered.")
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
            return MatchResul
