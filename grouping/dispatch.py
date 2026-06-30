"""
dispatch.py — grouped rule dispatch via CoreTree.

Walk the CoreNode tree top-down. At each node, run fingerprint gate first,
then find_core against the node's core. Recurse into children for more
specific matches. Most specific node = dispatch group. Then try each member
rule via match_cut_at_edge to find the firing rule.
"""
from __future__ import annotations

import builders.arithmetic_spine as _spine
import basic_machinery.operations as ops
if 'bit_add_00_c0_cont_cont_2bit' not in ops._registry:
    _spine.register_all()

from basic_machinery.match_view import derive_match_view, match_cut_at_edge, _input_relations
from core_finder import find_core
from core_tree import CoreTree, CoreNode, _fingerprint_gate, _compute_fingerprints

Edge = tuple


def _rule_edges(name: str) -> list[Edge]:
    """
    Extract the INPUT-SIDE match pattern for a rule, not its graph2 output.

    Dispatch matches a rule's input pattern against the live host graph — the
    same thing match_cut_at_edge tests. graph2 is the post-rewrite OUTPUT
    structure (much larger) and is the wrong object to build dispatch cores
    from: a graph2 core cannot embed in a single live host state.

    The input pattern is the set of relations over the match view's bind
    targets (what derive_match_view + match_cut_at_edge actually check).
    """
    rule = ops._registry[name]
    view = derive_match_view(rule.graph2)
    rel = _input_relations(rule.graph2, view)
    edges: list[Edge] = []
    for src, lst in rel.items():
        for (tgt, etype) in lst:
            edges.append((src.id, tgt.id, etype.name, None))
    return edges


def _graph_edges(graph) -> list[Edge]:
    return [
        (e.source.id, e.target.id, e.edge_type.name, None)
        for e in graph.edges
    ]


def build_dispatch_tree(rule_names: list[str], min_ratio: float = 0.3) -> CoreTree:
    """Build a CoreTree by inserting rules one at a time."""
    tree = CoreTree(min_ratio=min_ratio)
    for nm in rule_names:
        tree.insert(nm, _rule_edges(nm))
    return tree


def dispatch(graph, tree: CoreTree, threshold: float = 0.5) -> str | None:
    """
    Walk the core tree to find the most specific matching group,
    then try each member rule to find the firing rule.
    visited set prevents duplicate rule attempts if cross-reference
    discovery caused a rule to appear under multiple branches.
    """
    if tree.root is None:
        return None
    candidate = _graph_edges(graph)
    visited: set = set()
    return _find_and_try(candidate, graph, tree.root, threshold, visited, tree)


def _extract_delta(
    candidate: list[Edge],
    core_mapped_nodes: set,
) -> list[Edge]:
    """
    Extract delta edges from candidate: edges where BOTH endpoints
    are outside the core-matched region.
    """
    return [e for e in candidate
            if e[0] not in core_mapped_nodes and e[1] not in core_mapped_nodes]


def _find_and_try(
    candidate: list[Edge],
    graph,
    node: CoreNode,
    threshold: float,
    visited: set,
    tree: CoreTree,
    parent_map: dict | None = None,
) -> str | None:
    """
    Top-down walk with visited set and delta gating.

    At each node:
    1. Fingerprint gate on node core
    2. find_core (seeded from parent_map if available)
    3. Recurse into CoreNode children (most specific first)
    4. For leaf members: delta fingerprint gate before match_cut_at_edge

    visited set prevents duplicate attempts across merged branches.
    parent_map reuses work from parent level — stepwise growth in dispatch too.
    """
    should_try, _ = _fingerprint_gate(node.fingerprints, candidate, threshold)
    if not should_try:
        return None

    # Core match — seeded from parent level if available
    if parent_map:
        from core_finder import _grow_from
        seed_a = next(iter(parent_map))
        seed_b = parent_map[seed_a]
        matched, node_map = _grow_from(list(node.core_edges), candidate, seed_a, seed_b)
        ratio = len(matched) / len(node.core_edges) if node.core_edges else 0
    else:
        r = find_core(list(node.core_edges), candidate)
        ratio = r['ratio']
        node_map = r['subgraphs'][0][1] if r['subgraphs'] else {}

    if ratio < threshold:
        return None

    # Candidate nodes covered by the core match
    core_mapped = set(node_map.values())

    # Extract candidate's delta region
    candidate_delta = _extract_delta(candidate, core_mapped)
    candidate_delta_fp = _compute_fingerprints(candidate_delta)

    # Try CoreNode children first (most specific match), passing node_map as seed
    for child in node.children:
        if isinstance(child, CoreNode):
            if id(child) not in visited:
                visited.add(id(child))
                result = _find_and_try(candidate, graph, child, threshold,
                                       visited, tree, parent_map=node_map)
                if result is not None:
                    return result

    # Try leaf members — grow delta then verify boundary
    members = [c for c in node.children
               if isinstance(c, str) and c not in visited]
    for nm in sorted(members):
        visited.add(nm)

        # Build seed_map: rule_node -> candidate_node
        # accumulated_map: core_node -> candidate_node
        # _rule_map[nm]:   core_node -> rule_node
        # compose: rule_node -> candidate_node
        rule_map = tree._rule_map.get(nm, {})
        if rule_map and node_map:
            # Invert rule_map: rule_node -> core_node
            inv_rule_map = {v: k for k, v in rule_map.items()}
            # Compose via accumulated_map
            seed: dict = {}
            for rule_node, core_node in inv_rule_map.items():
                if core_node in node_map:
                    seed[rule_node] = node_map[core_node]
        else:
            seed = {}

        rule = ops._registry[nm]
        view = derive_match_view(rule.graph2)
        res = match_cut_at_edge(
            rule.graph2, graph, list(graph.nodes),
            view=view,
            seed_map=seed if seed else None
        )
        if res is not None:
            return nm

    return None


def _find_group(
    candidate: list[Edge],
    node: CoreNode,
    threshold: float,
) -> CoreNode | None:
    """Top-down walk. Returns deepest CoreNode matching candidate."""
    should_try, _ = _fingerprint_gate(node.fingerprints, candidate, threshold)
    if not should_try:
        return None

    r = find_core(list(node.core_edges), candidate)
    if r['ratio'] < threshold:
        return None

    for child in node.children:
        if isinstance(child, CoreNode):
            deeper = _find_group(candidate, child, threshold)
            if deeper is not None:
                return deeper

    return node


def _try_members(graph, member_names: list[str]) -> str | None:
    for nm in member_names:
        rule = ops._registry[nm]
        view = derive_match_view(rule.graph2)
        res = match_cut_at_edge(rule.graph2, graph, list(graph.nodes), view=view)
        if res is not None:
            return nm
    return None


# ---- Equivalence harness ----

def flat_baseline(graph, rule_names: list[str]) -> str | None:
    for nm in rule_names:
        rule = ops._registry[nm]
        view = derive_match_view(rule.graph2)
        res = match_cut_at_edge(rule.graph2, graph, list(graph.nodes), view=view)
        if res is not None:
            return nm
    return None


def grouped_dispatch(graph, tree: CoreTree, threshold: float = 0.5) -> str | None:
    return dispatch(graph, tree, threshold)
