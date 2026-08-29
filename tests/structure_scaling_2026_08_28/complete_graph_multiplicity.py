"""Wie klein kann Vorkommen(b) gegenueber Vorkommen(S) werden?

Doppelzaehlung: Vorkommen(b) >= Vorkommen(S) * t_b / m, mit t_b = wie oft b in
EINEM S steckt und m = maximale Mehrfachverwendung eines b-Vorkommens.

m ist unbeschraenkt. Extremfall: vollstaendiger Graph, m = C(n-j, k-j).

HINWEIS: das hier zaehlt Einbettungen ueber FREIE TEILMENGEN. Bei physischen
Strukturen (Kugeln) ist m = 1 strukturell, weil verschiedene grosse Kugeln
verschiedene Mittelpunkte haben.
"""
import os, sys
R = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for p in ['', 'GA', 'grouping', 'builders', 'basic_machinery']:
    sys.path.insert(0, os.path.join(R, p))
from collections import Counter
from math import comb
from basic_machinery.graph import PerspectiveGraph, EdgeType
import structure_analysis as SA

n, k = 7, 4
g = PerspectiveGraph(); ns = [g.add_node() for _ in range(n)]
for i in range(n):
    for j in range(i + 1, n):
        g.add_edge(ns[i], ns[j], EdgeType.STRUCTURAL)

allg, _ = SA.find_structures(g, comb(k, 2))
c = Counter(len(s) for s in allg)
print(f"K{n}, Budget = Innenkanten einer {k}-Clique")
for j in sorted(c):
    assert c[j] == comb(n, j), f"j={j}: {c[j]} != C({n},{j})"
    print(f"  j={j}: {c[j]:>4} Vorkommen = C({n},{j})")
print()
for j in range(1, k):
    m = comb(n - j, k - j)
    print(f"  m fuer j={j} in k={k}: C({n-j},{k-j}) = {m}")
assert c[k] > c[1], "Extremfall greift nicht"
print(f"\nAlle Unterstrukturen seltener als die {k}-Clique; m waechst mit n ohne Schranke.")
