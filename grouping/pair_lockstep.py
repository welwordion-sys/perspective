"""Lockstep-Kern: beide Seiten wachsen entlang von Kanten zusammen.

Kandidaten fuer den naechsten A-Frontier-Knoten a = B-Knoten, die zu
mindestens einem B-Bild eines BEREITS GEBUNDENEN A-Nachbarn von a
benachbart sind (struktur-egal, ungerichtet). Das ist Svens Lockstep:
nicht "alle freien B-Knoten" (enum_core2, Verzweigung ~|B|), sondern nur
die, die das B-Bild fortsetzen (Verzweigung ~Nachbarschaft).

use_exclude schaltet den "diesen Knoten in diesem Embedding nie binden"-
Zweig. enum_core2 hatte ihn, weil greedy-Sorge: ein ausgelassener Knoten
koennte spaeter matchen. Da Lockstep NICHT greedy ist (alle Seeds, alle
Lockstep-Zweige), ist der Zweig moeglicherweise ueberfluessig — genau das
testet sweep_lockstep gegen die Brute-Force-Referenz.
"""
from collections import defaultdict


def _adj(edges):
    a = defaultdict(set)
    for s, t, k, y in edges:
        a[s].add(t); a[t].add(s)
    return a


def _matched(A_edges, node_map, b_set):
    out = set()
    for e in A_edges:
        s, t, k, y = e
        bs, bt = node_map.get(s), node_map.get(t)
        if bs is not None and bt is not None and (bs, bt, k, y) in b_set:
            out.add(e)
    return frozenset(out)


def enumerate_lockstep(A_edges, B_edges, seed_a, seed_b, use_exclude=True):
    b_set = set(B_edges)
    aadj = _adj(A_edges)
    badj = _adj(B_edges)
    results = {}

    def expand(node_map, node_map_r, excluded):
        frontier = []
        for a in node_map:
            for o in aadj[a]:
                if o not in node_map and o not in excluded and o not in frontier:
                    frontier.append(o)
        if not frontier:
            m = _matched(A_edges, node_map, b_set)
            used = {seed_a}
            for e in m:
                used.add(e[0]); used.add(e[1])
            nm_used = {k: v for k, v in node_map.items() if k in used}
            # Seed-Bindungskomponente (Vertrag)
            comp = {seed_a}; changed = True
            while changed:
                changed = False
                for e in A_edges:
                    es, et = e[0], e[1]
                    if es in nm_used and et in nm_used and (es in comp) != (et in comp):
                        comp.add(es); comp.add(et); changed = True
            m = frozenset(e for e in m if e[0] in comp and e[1] in comp)
            nm_used = {k: v for k, v in nm_used.items() if k in comp}
            key = (m, tuple(sorted(nm_used.items())))
            results[key] = (m, nm_used)
            return

        a_node = min(frontier)
        # Lockstep-Kandidaten: B-Nachbarn der B-Bilder gebundener A-Nachbarn
        imgs = {node_map[a2] for a2 in aadj[a_node] if a2 in node_map}
        cands = set()
        for bimg in imgs:
            cands |= badj[bimg]
        cands = {c for c in cands if c not in node_map_r}

        for c in sorted(cands):
            nm = dict(node_map); nm[a_node] = c
            nmr = dict(node_map_r); nmr[c] = a_node
            expand(nm, nmr, excluded)
        if use_exclude:
            expand(node_map, node_map_r, excluded | {a_node})

    expand({seed_a: seed_b}, {seed_b: seed_a}, frozenset())

    out = list(results.values())
    keep = []
    for i, (m1, map1) in enumerate(out):
        dom = False
        for j, (m2, map2) in enumerate(out):
            if i == j:
                continue
            if (m1 < m2 and all(map2.get(k) == v for k, v in map1.items())) or \
               (m1 == m2 and set(map1.items()) < set(map2.items())):
                dom = True; break
        if not dom:
            keep.append((m1, map1))
    return keep
