"""Test gegen die ECHTEN Repo-Typen. Kein Nachbau eigener Graph-Klassen.

ZWECK: prüft structure_analysis.py gegen PerspectiveGraph.
VERDRAHTUNGSSTATUS: NOT ON SOLVE PATH — Testmodul, ruft nur.
ABHÄNGIGKEITEN: structure_analysis, basic_machinery.graph (notfalls reference/).
Der hier gebaute spine() ist ein NACHBAU der Kodierung, nicht encoding.py.
"""
import os, sys
_R = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in ["", "ga", "grouping", "builders", "basic_machinery"]:
    _q = os.path.join(_R, _p)
    if _q not in sys.path:
        sys.path.insert(0, _q)

# Cold-Start: Referenzkopie von basic_machinery beilegen, falls das echte Repo
# nicht im Pfad ist. Bei Abweichung gilt das Repo (siehe reference/HERKUNFT.md).
try:
    import basic_machinery  # noqa: F401
except ModuleNotFoundError:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reference'))
from basic_machinery.graph import PerspectiveGraph, EdgeType
from structure_analysis import *

def spine(bits, lval, rval):
    """Spine-Kodierung MIT PerspectiveGraph gebaut, nicht mit eigenem Typ."""
    g = PerspectiveGraph()
    ring = [g.add_node() for _ in range(4)]
    for i in range(4):
        g.add_edge(ring[i], ring[(i+1) % 4], EdgeType.STRUCTURAL)
    anchor = g.add_node()
    g.add_edge(ring[0], anchor, EdgeType.STRUCTURAL)
    for port, val in ((0, lval), (1, rval)):
        prev = None
        for i in range(bits):
            s = g.add_node(); leaf = g.add_node()
            g.add_edge(s, leaf, EdgeType.OPERATIONAL)
            if (val >> i) & 1:
                g.add_edge(leaf, leaf, EdgeType.STRUCTURAL)
            if prev: g.add_edge(prev, s, EdgeType.STRUCTURAL)
            else:    g.add_edge(ring[port], s, EdgeType.OPERATIONAL)
            prev = s
    return g

g = spine(4, 5, 3)
print(f"Graph: {len(g.nodes)} Knoten, {len(g.edges)} Kanten")
print(f"Selbstschleifen im Medium: {medium_has_self_loops(g)}")
print(f"Kantentypen im Medium: {[t.name for t in edge_types_in(g)]}")

# ungerichtete Nachbarschaft muss sich von der gerichteten unterscheiden
nb = undirected_adjacency(g)
some = next(n for n in g.nodes if len(nb[n]) > len(g.neighbors(n)))
print(f"gerichtet vs ungerichtet unterscheiden sich: OK "
      f"({len(g.neighbors(some))} vs {len(nb[some])})")

allg, maxk = find_structures(g, budget=4)
print(f"\nPhase 1: {len(allg)} Strukturen, {len(maxk)} max-k")
assert all(n_inner(g, s) <= 4 for s in allg), "Budget verletzt"
assert all(all(n_inner(g, frozenset(s|{u})) > 4 for u in frontier(g, s, nb))
           for s in maxk), "max-k nicht maximal"
print("  Invarianten Budget + Maximalitaet: OK")

bf = group_by_form(g, maxk)
print(f"Formen: {len(bf)}  ({len(maxk)/len(bf):.1f} Stellen je Form)")

cors = correlate(g, maxk, min_share=0.02)
print(f"Korrelationen: {len(cors)}, Verbundgroessen {sorted({c.joint_size for c in cors})}")
asym = {}
for c in cors: asym.setdefault(c.joint, []).append(c.coverage)
mehr = [v for v in asym.values() if len(v) >= 2 and max(v)-min(v) > 0.3]
print(f"  asymmetrische Paare: {len(mehr)}"
      + (f", Beispiel {max(mehr[0]):.0%} vs {min(mehr[0]):.0%}" if mehr else ""))

s = max(maxk, key=len)
f, cross = classify(g, s)
print(f"Phase 3: {len(s)} Knoten, Aussensignatur {cross}")

print(f"\nEntropie: {form_entropy(g,4):.2f} | Formen: {len(form_spectrum(g,4))}")

# Bezugsklasse — exakt, gegen die dokumentierten Zahlen
print("\nBezugsklasse exakt (2 Typen, Selbstschleifen erlaubt):")
for k,e,soll_kerne,soll_formen in ((4,3,1024,52),(4,4,16640,751),(5,4,32000,331)):
    tot, per = core_class(k,e,2,True)
    ok = "OK" if (tot==soll_kerne and len(per)==soll_formen) else "ABWEICHUNG"
    print(f"  k={k},e={e}: {tot:>7,} Kerne / {len(per):>4} Formen   {ok}")

print(f"  Anhang k=5,j=3: {pendant_factor(5,3,2):,.1f}")
print(f"  Bezugsklasse k=5,e=4,j=3: {reference_class_size(5,4,3,2,True):,.0f}")

# echte Struktur durchrechnen
klein = [x for x in maxk if len(x)==5 and n_inner(g,x)==4]
if klein:
    p = structure_probability(g, klein[0])
    print(f"  P(echte 5-Knoten-Struktur): {p:.3e}")

print("\nTESTS DURCH")
