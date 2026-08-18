"""Erzeugt die im Gesamtdesign und in strukturanalyse_design.md zitierten Zahlen neu.

Pflicht nach meta.handoff_preflight Regel 5: jede zitierte Zahl nennt ein Skript
im Paket, das sie regeneriert.

    python3 reproduce_measurements.py

GELTUNGSBEREICH JEDER ZAHL — wichtig, weil zwei richtige Zahlen ohne diese Angabe
wie ein Widerspruch aussehen (meta.handoff_preflight, C_general_principles):
Alle Graphenzahlen stammen aus einem NACHBAU der Spine-Kodierung (Funktion
spine() unten), NICHT aus encoding.py. Größenordnungen tragen, genaue
Formzahlen nicht. Die Bezugsklassenzahlen (core_class) sind dagegen reine
Kombinatorik und vom Substrat unabhängig — die gelten absolut.
"""
import os, sys, random
_R = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in ["", "ga", "grouping", "builders", "basic_machinery"]:
    _q = os.path.join(_R, _p)
    if _q not in sys.path:
        sys.path.insert(0, _q)

try:
    import basic_machinery  # noqa: F401
except ModuleNotFoundError:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reference'))

from basic_machinery.graph import PerspectiveGraph, EdgeType
from structure_analysis import (find_structures, form, group_by_form, correlate,
                                form_entropy, form_spectrum, core_class,
                                pendant_factor, reference_class_size,
                                n_inner, undirected_adjacency, frontier)

def spine(bits, lval, rval):
    """NACHBAU der Spine-Kodierung. Nicht encoding.py."""
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

def random_like(g, rng):
    """ABSOLUTER Zufall: gleiche Knoten- und Kantenzahl, Typen gleichverteilt."""
    types = [EdgeType.STRUCTURAL, EdgeType.OPERATIONAL]
    r = PerspectiveGraph()
    mapping = [r.add_node() for _ in g.nodes]
    want, have = len(g.edges), set()
    while len(have) < want:
        have.add((rng.choice(mapping), rng.choice(mapping), rng.choice(types)))
    for u, v, t in have:
        r.add_edge(u, v, t)
    return r

FAIL = []
def check(label, got, want, tol=0):
    ok = abs(got - want) <= tol if isinstance(want, (int, float)) else got == want
    print(f"  {'OK ' if ok else 'ABW'} {label:52s} {got}" + ("" if ok else f"  erwartet {want}"))
    if not ok: FAIL.append(label)

print(__doc__.split("GELTUNGSBEREICH")[0].strip())
print("\n=== 1. Aufzaehlung, Budget 4, Nachbau 4-Bit ===")
g = spine(4, 5, 3)
check("Knoten", len(g.nodes), 21)
check("Kanten", len(g.edges), 25)
allg, maxk = find_structures(g, 4)
check("Strukturen gesamt", len(allg), 159)
check("max-k", len(maxk), 56)
check("verschiedene Formen", len(group_by_form(g, maxk)), 35)

print("\n=== 2. Invarianten ===")
nb = undirected_adjacency(g)
check("alle innerhalb Budget", all(n_inner(g, s) <= 4 for s in allg), True)
check("max-k wirklich maximal",
      all(all(n_inner(g, frozenset(s | {u})) > 4 for u in frontier(g, s, nb))
          for s in maxk), True)

print("\n=== 3. Korrelation, Asymmetrie ===")
cors = correlate(g, maxk, min_share=0.02)
sizes = sorted({c.joint_size for c in cors})
check("Verbundgroessen k+1..2k", sizes, [5, 6, 7, 8, 9, 10])
asym = {}
for c in cors: asym.setdefault(c.joint, []).append(c.coverage)
mehr = [v for v in asym.values() if len(v) >= 2 and max(v) - min(v) > 0.3]
print(f"      asymmetrische Paare: {len(mehr)}"
      + (f", Beispiel {max(mehr[0]):.0%} vs {min(mehr[0]):.0%}" if mehr else ""))

# Invarianz gegen die Indexvergabe. Genau das war 2026-08-14 verletzt: ein
# `i<j`-Filter warf eine der beiden Korrelationsrichtungen weg, und WELCHE
# haeng an der Reihenfolge von max_k. Ergebnis schwankte 599-669 / 12-19.
# Der Test gehoert hierher, weil die Zahl sonst stabil AUSSIEHT (Node hasht
# deterministisch) und der Fehler unsichtbar bleibt.
def _korr_kennzahl(order_seed):
    mk = list(maxk)
    random.Random(order_seed).shuffle(mk)
    cs = correlate(g, mk, min_share=0.02)
    a = {}
    for c in cs: a.setdefault(c.joint, []).append(c.coverage)
    return len(cs), len([1 for v in a.values() if len(v) >= 2 and max(v) - min(v) > 0.3])

_kz = [_korr_kennzahl(s) for s in range(5)]
check("unabhaengig von der Indexvergabe", len(set(_kz)), 1)
print(f"      fuenf Indexvergaben -> {_kz[0][0]} Korrelationen, "
      f"{_kz[0][1]} asymmetrische Paare, jedes Mal")

print("\n=== 4. Entropie: Substrat gegen absoluten Zufall ===")
e_real = form_entropy(g, 4); v_real = len(form_spectrum(g, 4))
rng = random.Random(3)
zs = [(form_entropy(r, 4), len(form_spectrum(r, 4)))
      for r in (random_like(g, rng) for _ in range(15))]
print(f"      Entropie  echt {e_real:.2f} | Zufall {sum(z[0] for z in zs)/len(zs):.2f}")
print(f"      Formen    echt {v_real}    | Zufall {sum(z[1] for z in zs)/len(zs):.1f}")
print("      -> die EINSCHRAENKUNG des Formenraums ist die Information")

print("\n=== 5. Bezugsklasse, exakt (2 Typen, Selbstschleifen erlaubt) ===")
print("      substratunabhaengig, reine Kombinatorik")
for k, e, sk, sf in ((4,3,1024,52), (4,4,16640,751), (5,4,32000,331)):
    tot, per = core_class(k, e, 2, True)
    check(f"k={k},e={e} Kerne", tot, sk)
    check(f"k={k},e={e} Formen", len(per), sf)
check("Anhang k=5,j=3 (durch 3! geteilt)", round(pendant_factor(5,3,2),1), 1333.3, 0.1)
check("Bezugsklasse k=5,e=4,j=3", round(reference_class_size(5,4,3,2,True)), 42666667, 1)

print("\n" + ("ALLE ZAHLEN REPRODUZIERT" if not FAIL
              else f"ABWEICHUNGEN: {FAIL}"))
sys.exit(1 if FAIL else 0)
