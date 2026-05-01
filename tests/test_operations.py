import pytest
from basic_machinery.graph import PerspectiveGraph, Node, Edge, EdgeType
from basic_machinery.operations import (
    MatchResult,
    OperationDefinition,
    match,
    match_all,
    apply,
    snapshot,
    revert,
    register,
    lookup,
)


def make_two_node_graph(edge_type: EdgeType) -> tuple[PerspectiveGraph, Node, Node]:
    g = PerspectiveGraph()
    a = g.add_node()
    b = g.add_node()
    g.add_edge(a, b, edge_type)
    return g, a, b


def test_match_finds_single_edge_pattern():
    g, a, b = make_two_node_graph(EdgeType.STRUCTURAL)
    pattern, pa, pb = make_two_node_graph(EdgeType.STRUCTURAL)

    result = match(g, pattern)

    assert result.success
    assert len(result.node_map) == 2


def test_match_fails_wrong_edge_type():
    g, a, b = make_two_node_graph(EdgeType.STRUCTURAL)
    pattern, pa, pb = make_two_node_graph(EdgeType.OPERATIONAL)

    result = match(g, pattern)

    assert not result.success


def test_match_fails_pattern_larger_than_graph():
    g = PerspectiveGraph()
    g.add_node()

    pattern, pa, pb = make_two_node_graph(EdgeType.STRUCTURAL)

    result = match(g, pattern)

    assert not result.success


def test_match_empty_pattern_always_succeeds():
    g, a, b = make_two_node_graph(EdgeType.STRUCTURAL)
    pattern = PerspectiveGraph()

    result = match(g, pattern)

    assert result.success

def test_match_all_finds_both_directions():
    g, a, b = make_two_node_graph(EdgeType.STRUCTURAL)
    g.add_edge(b, a, EdgeType.STRUCTURAL)

    pattern, _, _ = make_two_node_graph(EdgeType.STRUCTURAL)

    results = match_all(g, pattern)

    assert len(results) == 2


def test_match_all_returns_empty_on_no_match():
    g, _, _ = make_two_node_graph(EdgeType.STRUCTURAL)
    pattern, _, _ = make_two_node_graph(EdgeType.OPERATIONAL)

    results = match_all(g, pattern)

    assert len(results) == 0

def test_apply_executes_rewrite_on_match():
    g, a, b = make_two_node_graph(EdgeType.STRUCTURAL)

    added_nodes = []

    def rewrite(graph: PerspectiveGraph, result: MatchResult) -> None:
        added_nodes.append(graph.add_node())

    op = OperationDefinition(name="test_op", pattern=PerspectiveGraph(), rewrite=rewrite)

    success, _ = apply(g, op)

    assert success
    assert len(added_nodes) == 1
    assert len(g.nodes) == 3


def test_apply_skips_rewrite_on_no_match():
    g, _, _ = make_two_node_graph(EdgeType.STRUCTURAL)
    pattern, _, _ = make_two_node_graph(EdgeType.OPERATIONAL)

    def rewrite(graph: PerspectiveGraph, result: MatchResult) -> None:
        graph.add_node()

    op = OperationDefinition(name="test_op_2", pattern=pattern, rewrite=rewrite)

    success, _ = apply(g, op)

    assert not success
    assert len(g.nodes) == 2


def test_revert_restores_graph():
    g, a, b = make_two_node_graph(EdgeType.STRUCTURAL)
    snap = snapshot(g)

    g.add_node()
    assert len(g.nodes) == 3

    revert(g, snap)
    assert len(g.nodes) == 2