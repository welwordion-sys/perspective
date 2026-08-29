"""Wie viele Paare teilen sich dieselbe VEREINIGUNG?
(A-e)+(B+e) und A+B ergeben dasselbe U. Die teure Operation ist form(U).
"""
import os, sys, time
R='/home/claude/repo'
for p in ['','GA','grouping','builders','basic_machinery']: sys.path.insert(0,os.path.join(R,p))
from basic_machinery.graph import PerspectiveGraph, EdgeType
from collections import Counter, defaultdict
import structure_analysis as SA
S=EdgeType.STRUCTURAL; O=EdgeType.OPERATIONAL

W=H=12
on=set((x,1) for x in range(2,10))|set((6,y) for y in range(1,11))
g=PerspectiveGraph(); nd={}
for y in range(H):
    for x in range(W): nd[(x,y)]=g.add_node()
for y in range(H):
    for x in range(W):
        if x+1<W: g.add_edge(nd[(x,y)],nd[(x+1,y)],S)
        if y+1<H: g.add_edge(nd[(x,y)],nd[(x,y+1)],S)
for (x,y),n in nd.items():
    t=g.add_node(); g.add_edge(n,t,O)
    if (x,y) in on: g.add_edge(t,t,S)
nb=SA.undirected_adjacency(g)
def kugeln(budget):
    out=set()
    for v in g.nodes:
        ball={v}; rand={v}
        while True:
            if SA.n_inner(g,frozenset(ball))>budget: break
            out.add(frozenset(ball))
            neu={u for x in rand for u in nb.get(x,())}-ball
            if not neu: break
            k=ball|neu
            if SA.n_inner(g,frozenset(k))>budget: break
            ball=k; rand=neu
    return out

for budget in (8,16):
    ks=list(kugeln(budget)); idx=SA.node_index(ks)
    paare=[]; 
    for i in range(len(ks)):
        for j in SA.touching(g,ks,idx,i,nb):
            if i<j: paare.append((i,j))
    unionen=defaultdict(list)
    for i,j in paare: unionen[frozenset(ks[i]|ks[j])].append((i,j))
    t0=time.time(); formen={u:SA.form(g,u) for u in unionen}; t_ein=time.time()-t0
    print(f"Kugelbudget {budget}: {len(ks)} Kugeln | Paare {len(paare):,} | "
          f"verschiedene Vereinigungen {len(unionen):,} | Verbundformen {len(set(formen.values())):,}")
    vt=Counter(len(v) for v in unionen.values())
    print(f"   Paare je Vereinigung: {dict(sorted(vt.items())[:6])} ...")
    print(f"   form() Aufrufe: mit Cache {len(unionen):,} statt {len(paare):,} "
          f"-> {100*(1-len(unionen)/len(paare)):.0f}% gespart, Rechenzeit {t_ein:.1f}s")
