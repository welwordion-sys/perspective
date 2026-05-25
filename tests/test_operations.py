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
)


def make_two_node_graph(edge_type: EdgeType) -> tuple[PerspectiveGraph, Node, Node]:
    g = PerspectiveGraph()
    a = g.add_node()
    b = g.add_node()
    g.add_edge(a, b, edge_type)
    return g, a, b


# ---------------------------------------------------------------------------
# match()
# ---------------------------------------------------------------------------

def test_match_finds_single_edge_pattern():
    g, a, b = make_two_node_graph(EdgeType.STRUCTURAL)
    pattern, pa, pb = make_two_node_graph(EdgeType.STRUCTURAL)
    result = match(pattern, g)
    assert result.success
    assert len(result.node_map) == 2


def test_match_fails_wrong_edge_type():
    g, a, b = make_two_node_graph(EdgeType.STRUCTURAL)
    pattern, pa, pb = make_two_node_graph(EdgeType.OPERATIONAL)
    result = match(pattern, g)
    assert not result.success


def test_match_fails_pattern_larger_than_graph():
    g = PerspectiveGraph()
    g.add_node()
    pattern, pa, pb = make_two_node_graph(EdgeType.STRUCTURAL)
    result = match(pattern, g)
    assert not result.success


def test_match_empty_pattern_always_succeeds():
    g, a, b = make_two_node_graph(EdgeType.STRUCTURAL)
    pattern = PerspectiveGraph()
    result = match(pattern, g)
    assert result.success


# ---------------------------------------------------------------------------
# match_all()
# ---------------------------------------------------------------------------

def test_match_all_finds_both_directions():
    g, a, b = make_two_node_graph(EdgeType.STRUCTURAL)
    g.add_edge(b, a, EdgeType.STRUCTURAL)
    pattern, _, _ = make_two_node_graph(EdgeType.STRUCTURAL)
    results = match_all(pattern, g)
    assert len(results) == 2


def test_match_all_returns_empty_on_no_match():
    g, _, _ = make_two_node_graph(EdgeType.STRUCTURAL)
    pattern, _, _ = make_two_node_graph(EdgeType.OPERATIONAL)
    results = match_all(pattern, g)
    assert len(results) == 0


# ---------------------------------------------------------------------------
# apply() — triple schema (pattern, graph2s, graph2o)
# ---------------------------------------------------------------------------

def _make_add_node_op() -> OperationDefinition:
    """
    Trivial rule: matches a single structural edge A->B,
    graph2s: A->B survive (input→output pairs), graph2o: empty.
    Just verifies apply() fires and returns True.
    """
    pattern = PerspectiveGraph()
    pa = pattern.add_node()
    pb = pattern.add_node()
    pattern.add_edge(pa, pb, EdgeType.STRUCTURAL)

    # graph2s: strip OPERATIONAL (none here), output STRUCTURAL
    # Input: pa, pb. Output: pa_out, pb_out. Both survive unchanged.
    g2s = PerspectiveGraph()
    pa_in = g2s.add_node()
    pb_in = g2s.add_node()
    pa_out = g2s.add_node()
    pb_out = g2s.add_node()
    g2s.add_edge(pa_in, pa_out, EdgeType.OPERATIONAL)
    g2s.add_edge(pb_in, pb_out, EdgeType.OPERATIONAL)
    g2s.add_edge(pa_out, pb_out, EdgeType.STRUCTURAL)

    g2o = PerspectiveGraph()

    return OperationDefinition(name='test_survive', pattern=pattern, graph2s=g2s, graph2o=g2o)


def test_apply_returns_true_on_match():
    g, a, b = make_two_node_graph(EdgeType.STRUCTURAL)
    op = _make_add_node_op()
    assert apply(g, op)


def test_apply_returns_false_on_no_match():
    g, a, b = make_two_node_graph(EdgeType.STRUCTURAL)
    pattern, _, _ = make_two_node_graph(EdgeType.OPERATIONAL)
    g2s = PerspectiveGraph()
    g2o = PerspectiveGraph()
    op = OperationDefinition(name='test_no_match', pattern=pattern, graph2s=g2s, graph2o=g2o)
    assert not apply(g, op)


def test_apply_graph_unchanged_on_no_match():
    g, a, b = make_two_node_graph(EdgeType.STRUCTURAL)
    nodes_before = set(g.nodes)
    edges_before = set(g.edges)
    pattern, _, _ = make_two_node_graph(EdgeType.OPERATIONAL)
    g2s = PerspectiveGraph()
    g2o = PerspectiveGraph()
    op = OperationDefinition(name='test_no_change', pattern=pattern, graph2s=g2s, graph2o=g2o)
    apply(g, op)
    assert g.nodes == nodes_before
    assert g.edges == edges_before


# ---------------------------------------------------------------------------
# snapshot / revert
# ---------------------------------------------------------------------------

def test_revert_restores_graph():
    g, a, b = make_two_node_graph(EdgeType.STRUCTURAL)
    snap = snapshot(g)
    g.add_node()
    assert len(g.nodes) == 3
    revert(g, snap)
    assert len(g.nodes) == 2
