"""
core_finder7.py — exhaustive seed-pair MCS finder.

For each unmapped A-node, try every unmapped B-node as a seed.
Grow maximum lockstep subgraph from each pair.
Accept the best result, mark those nodes as mapped.
Repeat with remaining unmapped nodes until exhausted.

Growth: from seed pair (a, b), follow every possible lockstep edge —
both endpoints must be either unmapped or already consistently mapped.
Greedy: exhaust all edges from current node before moving to next.
No binding committed until an edge actually locksteps.
"""
from __future__ import annotations
from collections import defaultdict
from typing import Any
import random

Edge = tuple  # (src, tgt, kind, type)


def _node_edges(edges: list[Edge]) -> dict[Any, list[Edge]]:
    idx: dict[Any, list[Edge]] = {}
    for e in edges:
        idx.setdefault(e[0], []).append(e)
        if e[1] != e[0]:
            idx.setdefault(e[1], []).append(e)
    return idx


def _grow_from(
    A_edges: list[Edge],
    B_edges: list[Edge],
    seed_a: Any,
    seed_b: Any,
) -> tuple[set[Edge], dict[Any, Any]]:
    """
    Grow maximum lockstep subgraph from (seed_a, seed_b).
    Returns (matched_a_edges, node_map: a->b).
    No randomness — deterministic greedy growth.
    """
    a_idx = _node_edges(A_edges)
    b_idx = _node_edges(B_edges)
    b_set = set(B_edges)

    node_map: dict[Any, Any] = {seed_a: seed_b}
    node_map_r: dict[Any, Any] = {seed_b: seed_a}
    matched: set[Edge] = set()
    frontier: list[Any] = [seed_a]
    visited_edges: set[Edge] = set()

    while frontier:
        # Greedy: exhaust current node before moving on
        a_node = frontier[0]
        b_node = node_map[a_node]
        grew = False

        for ae in a_idx.get(a_node, []):
            if ae in visited_edges:
                continue
            a_src, a_tgt, kind, typ = ae

            if a_src == a_tgt:
                # Self-edge
                visited_edges.add(ae)
                be = (b_node, b_node, kind, typ)
                if be in b_set:
                    matched.add(ae)
                continue

            other_a = a_tgt if a_src == a_node else a_src
            direction_out = (a_src == a_node)

            # If other_a already mapped, check consistency
            if other_a in node_map:
                visited_edges.add(ae)
                other_b = node_map[other_a]
                be = (b_node, other_b, kind, typ) if direction_out else (other_b, b_node, kind, typ)
                if be in b_set:
                    matched.add(ae)
                continue

            # other_a not yet mapped — find B-candidates
            if direction_out:
                cands = [be[1] for be in b_idx.get(b_node, [])
                         if be[2]==kind and be[3]==typ
                         and be[0]==b_node and be[1]!=b_node
                         and be[1] not in node_map_r]
            else:
                cands = [be[0] for be in b_idx.get(b_node, [])
                         if be[2]==kind and be[3]==typ
                         and be[1]==b_node and be[0]!=b_node
                         and be[0] not in node_map_r]

            if not cands:
                visited_edges.add(ae)
                continue

            # Pick candidate with most edges in common with already-mapped neighbours
            def score_cand(bn):
                s = 0
                for ae2 in a_idx.get(other_a, []):
                    nbr = ae2[1] if ae2[0]==other_a else ae2[0]
                    if nbr in node_map:
                        mapped_b = node_map[nbr]
                        direction_out2 = (ae2[0]==other_a)
                        be2 = (bn, mapped_b, ae2[2], ae2[3]) if direction_out2 \
                              else (mapped_b, bn, ae2[2], ae2[3])
                        if be2 in b_set:
                            s += 1
                return s

            chosen = max(cands, key=score_cand)
            node_map[other_a] = chosen
            node_map_r[chosen] = other_a
            visited_edges.add(ae)

            be = (b_node, chosen, kind, typ) if direction_out else (chosen, b_node, kind, typ)
            if be in b_set:
                matched.add(ae)

            if other_a not in frontier:
                frontier.append(other_a)
            grew = True

        if not grew or all(ae in visited_edges for ae in a_idx.get(a_node, [])):
            frontier.pop(0)

    return matched, node_map


def find_core(
    A_edges: list[Edge],
    B_edges: list[Edge],
    min_ratio: float = 0.3,
) -> dict:
    """
    Find core by exhaustive seed-pair search with progressive node elimination.

    For each unmapped A-node, try every unmapped B-node as seed.
    Accept best result if it meets min_ratio threshold.
    Repeat until all nodes exhausted.

    Returns:
        safe_core   — edges in confirmed subgraph mappings
        contested   — edges found in subgraphs below threshold
        subgraphs   — list of (matched_edges, node_map) for each accepted mapping
        ratio       — core nodes / total A-nodes
    """
    A_nodes = list({n for e in A_edges for n in (e[0], e[1])})
    B_nodes = list({n for e in B_edges for n in (e[0], e[1])})

    unmapped_a = set(A_nodes)
    unmapped_b = set(B_nodes)

    subgraphs = []
    safe_core: set[Edge] = set()
    contested:  set[Edge] = set()

    while unmapped_a:
        best_matched: set[Edge] = set()
        best_map: dict = {}
        best_size = 0

        # Try each unmapped A-node against each unmapped B-node
        for a0 in list(unmapped_a):
            for b0 in list(unmapped_b):
                matched, node_map = _grow_from(A_edges, B_edges, a0, b0)
                # Only count edges where both endpoints are unmapped or newly mapped
                valid = {e for e in matched
                         if node_map.get(e[0]) is not None
                         and node_map.get(e[1]) is not None}
                if len(valid) > best_size:
                    best_size = len(valid)
                    best_matched = valid
                    best_map = node_map

        if not best_matched:
            break

        # Check if best result meets threshold
        mapped_a = set(best_map.keys())
        ratio = len(mapped_a & unmapped_a) / len(unmapped_a)

        if ratio >= min_ratio:
            subgraphs.append((best_matched, best_map))
            safe_core |= best_matched
            # Remove mapped nodes from search
            unmapped_a -= set(best_map.keys())
            unmapped_b -= set(best_map.values())
        else:
            # Below threshold — mark as contested, stop
            contested |= best_matched
            break

    total_a = len(A_nodes)
    core_nodes = {n for e in safe_core for n in (e[0], e[1])}
    ratio = len(core_nodes) / total_a if total_a else 0

    return dict(
        safe_core=safe_core,
        contested=contested,
        subgraphs=subgraphs,
        ratio=ratio,
    )
