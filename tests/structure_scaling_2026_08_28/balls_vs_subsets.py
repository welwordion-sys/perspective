"""Breite zuerst: nicht alle zusammenhaengenden Teilmengen, sondern vollstaendige
Kugeln. Erst ALLE Kanten im Abstand 1, dann Abstand 2, usw. Eine Struktur je
Mittelpunkt und Radius statt einer je Teilmenge.
"""
import os, sys, time
R='/home/claude/repo'
for p in ['','GA','grouping','builders','basic_machinery']: sys.path.insert(0,os.path.join(R,p))
from basic_machinery.graph import PerspectiveGraph, EdgeType
from collections import Counter, deque
import structure_analysis as SA

def grid(w,h,on=frozenset()):
    g=PerspectiveGraph(); node={}
    for y in range(h):
        for x in range(w): node[(x,y)]=g.add_node()
    for y in range(h):
        for x in range(w):
            if x+1<w: g.add_edge(node[(x,y)],node[(x+1,y)],EdgeType.STRUCTURAL)
            if y+1<h: g.add_edge(node[(x,y)],node[(x,y+1)],EdgeType.STRUCTURAL)
    for (x,y),n in node.items():
        t=g.add_node(); g.add_edge(n,t,EdgeType.OPERATIONAL)
        if (x,y) in on: g.add_edge(t,t,EdgeType.STRUCTURAL)
    return g

def kugeln(g, budget):
    """Alle vollstaendigen Kugeln B(v,r) mit n_inner <= budget."""
    nb = SA.undirected_adjacency(g)
    out = set()
    for v in g.nodes:
        ball = {v}; rand = {v}
        while True:
            if SA.n_inner(g, frozenset(ball)) > budget: break
            out.add(frozenset(ball))
            neu = {u for x in rand for u in nb.get(x, ())} - ball
            if not neu: break
            kandidat = ball | neu
            if SA.n_inner(g, frozenset(kandidat)) > budget: break
            ball = kandidat; rand = neu
    return out

on = set((x,1) for x in range(2,10)) | set((6,y) for y in range(1,11))
g = grid(12,12,frozenset(on))
print(f"12x12 'T': {len(g.nodes)} Knoten, {len(g.edges)} Kanten\n")
print(f"{'Budget':>7} {'Kugeln':>9} {'Formen':>8} {'groesste':>9} {'Zeit':>8}   Formhaeufigkeiten")
for b in (3,5,8,12,20,30):
    t0=time.time(); ks=kugeln(g,b)
    f=Counter(SA.form(g,s) for s in ks); dt=time.time()-t0
    gr=max((len(s) for s in ks), default=0)
    top=sorted(f.values(), reverse=True)[:6]
    print(f"{b:>7} {len(ks):>9,} {len(f):>8} {gr:>9} {dt:>7.1f}s   {top}")

print("\n=== Budget 30: Formhaeufigkeitsverteilung ===")
ks = kugeln(g, 30)
f = Counter(SA.form(g, s) for s in ks)
verteilung = Counter(f.values())
print(f"Kugeln {len(ks):,} | Formen {len(f)}")
print(f"{'Vorkommen':>10} {'Formen':>8} {'Kugeln':>8}")
for anzahl in sorted(verteilung):
    print(f"{anzahl:>10} {verteilung[anzahl]:>8} {anzahl*verteilung[anzahl]:>8}")
einzel = verteilung.get(1, 0)
print(f"\nEinzelstrukturen (Form kommt genau 1x vor): {einzel} von {len(f)} Formen "
      f"({100*einzel/len(f):.0f}%), das sind {einzel} von {len(ks):,} Kugeln "
      f"({100*einzel/len(ks):.1f}%)")
# Groessenverteilung der Einzelgaenger
einzelformen = {fo for fo, c in f.items() if c == 1}
groessen = sorted(len(s) for s in ks if SA.form(g, s) in einzelformen)
print(f"Knotenzahl der Einzelstrukturen: min {groessen[0]}, max {groessen[-1]}, "
      f"Median {groessen[len(groessen)//2]}")
