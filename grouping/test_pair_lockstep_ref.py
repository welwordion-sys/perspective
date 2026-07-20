"""Naive Referenz: ALLE maximalen Embeddings per Brute-Force.

Absichtlich dumm und unabhaengig vom Primitiv (o_indep aus naive_search):
zaehlt jede injektive Teilabbildung der A-Knoten auf B-Knoten auf,
berechnet matched direkt aus der Definition, behaelt die maximalen.
Nur fuer kleine Graphen tragbar — das ist ihr Zweck (oracle_run-Rolle).
"""
from itertools import permutations, combinations


def _nodes(edges):
    ns = set()
    for e in edges:
        ns.add(e[0]); ns.add(e[1])
    return sorted(ns)


def _matched(A_edges, node_map, b_set):
    out = set()
    for e in A_edges:
        s, t, k, y = e
        bs, bt = node_map.get(s), node_map.get(t)
        if bs is not None and bt is not None and (bs, bt, k, y) in b_set:
            out.add(e)
    return frozenset(out)


def naive_all_max(A_edges, B_edges, seed_a, seed_b):
    """Alle maximalen (matched, map) mit seed_a->seed_b, map injektiv."""
    a_nodes = [n for n in _nodes(A_edges) if n != seed_a]
    b_nodes = [n for n in _nodes(B_edges) if n != seed_b]
    b_set = set(B_edges)

    all_results = {}
    for r in range(len(a_nodes) + 1):
        for a_sub in combinations(a_nodes, r):
            for b_perm in permutations(b_nodes, r):
                nm = {seed_a: seed_b}
                nm.update(zip(a_sub, b_perm))
                m = _matched(A_edges, nm, b_set)
                # nur Knoten behalten, die an gematchten Kanten beteiligt
                # sind (sonst zaehlen wir irrelevante Bindungen als
                # verschiedene Embeddings)
                used = {seed_a}
                for e in m:
                    used.add(e[0]); used.add(e[1])
                nm_used = {k: v for k, v in nm.items() if k in used}
                key = (m, tuple(sorted(nm_used.items())))
                all_results[key] = (m, nm_used)

    out = list(all_results.values())
    keep = []
    for i, (m1, map1) in enumerate(out):
        dom = False
        for j, (m2, map2) in enumerate(out):
            if i == j: continue
            if m1 < m2 and all(map2.get(k) == v for k, v in map1.items()):
                dom = True; break
        if not dom:
            keep.append((m1, map1))
    return keep
