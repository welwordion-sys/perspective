"""
dispatch.py — grouped rule dispatch via core tree walk.

Walk the CoreNode tree top-down. At each node, run find_core(candidate,
representative_member_edges). If ratio >= threshold, recurse into children
to find the most specific (deepest) matching subgroup. If ratio < threshold,
stop — the candidate belongs to the parent group.

The most specific node whose core matches = the dispatch group.
Members of that group are then tried individually (match_cut_at_edge) to find
the firing rule.

Core = subgraph match result from find_core — maximum lockstep subgraph.
Delta = candidate edges not in the matched subgraph (extract_delta).
Cut is at the core boundary; delta edges attach to core nodes only.
"""
from __future__ import annotations
from typing import Any

import basic_machinery.operations as ops
import basic_machinery.arithmetic_spine as _spine
if not ops._registry:
    _spine.register_all()

from basic_machinery.match_view import derive_match_view, match_cut_at_edge
from core_finder import find_core
from core_tree import CoreNode, build_tree
from delta_extractor import extract_delta

Edge = tuple  # (src, tgt, kind, type)


def _rule_edges(name: str) -> list[Edge]:
    """Extract edge list from a registered rule's graph2."""
    rule = ops._registry[name]
    return [
        (e.source.id, e.target.id, e.edge_type.name, None)
        for e in rule.graph2.edges
    ]


def _graph_edges(graph) -> list[Edge]:
    """Extract edge list from a live PerspectiveGraph."""
    return [
        (e.source.id, e.target.id, e.edge_type.name, None)
        for e in graph.edges
    ]


def build_dispatch_tree(rule_names: list[str], min_members: int = 2) -> CoreNode:
    """
    Build a CoreNode tree from a set of registered rule names.
    graphs dict maps rule name -> edge list.
    """
    graphs = {nm: _rule_edges(nm) for nm in rule_names}
    return build_tree(graphs, min_members=min_members)


def dispatch(graph, tree: CoreNode, threshold: float = 0.5) -> str | None:
    """
    Walk the core tree top-down to find the most specific matching group,
    then try each member's real match to find the firing rule.

    Returns the name of the firing rule, or None.
    """
    candidate = _graph_edges(graph)
    node = _find_group(candidate, tree, threshold)
    if node is None:
        return None
    return _try_members(graph, sorted(node.members))


def _find_group(
    candidate: list[Edge],
    node: CoreNode,
    threshold: float,
) -> CoreNode | None:
    """
    Top-down walk. Returns the deepest CoreNode whose core matches candidate
    at >= threshold, or None if even the root doesn't match.
    """
    # Pick a representative member to compare against
    rep = next(iter(node.members))
    rep_edges = list(node.core_edges)  # core edges are in rep's ID space

    if not rep_edges:
        # Empty core (singleton or degenerate) — treat as match, try members
        return node

    r = find_core(rep_edges, candidate)
    if r['ratio'] < threshold:
        return None  # Doesn't match this node at all

    # Matches this node — try to go deeper
    for child in node.children:
        deeper = _find_group(candidate, child, threshold)
        if deeper is not None:
            return deeper

    # No child matched — this node is the most specific match
    return node


def _try_members(graph, member_names: list[str]) -> str | None:
    """Try each member's real match_cut_at_edge; return first that fires."""
    for nm in member_names:
        rule = ops._registry[nm]
        view = derive_match_view(rule.graph2)
        res = match_cut_at_edge(rule.graph2, graph, list(graph.nodes), view=view)
        if res is not None:
            return nm
    return None


# ---- Equivalence harness ----

def flat_baseline(graph, rule_names: list[str]) -> str | None:
    """Linear scan in registry order — what the engine does today."""
    for nm in rule_names:
        rule = ops._registry[nm]
        view = derive_match_view(rule.graph2)
        res = match_cut_at_edge(rule.graph2, graph, list(graph.nodes), view=view)
        if res is not None:
            return nm
    return None


def grouped_dispatch(graph, tree: CoreNode, threshold: float = 0.5) -> str | None:
    return dispatch(graph, tree, threshold)
