"""Haeufigkeit VOR Diagnose. Was bleibt uebrig, wenn beide Seiten haeufig sein
muessen? correlate filtert heute nur die QUELLform (min_share), nicht die
Verbundform -- ein Verbund, der einmal vorkommt, erzeugt trotzdem eine Zeile
mit coverage 1/1 = 100%.
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
def kugeln(b):
    out=set()
    for v in g.nodes:
        ball={v}; rand={v}
        while True:
            if SA.n_inner(g,frozenset(ball))>b: break
            out.add(frozenset(ball))
            neu={u for x in rand for u in nb.get(x,())}-ball
            if not neu: break
            k=ball|neu
            if SA.n_inner(g,frozenset(k))>b: break
            ball=k; rand=neu
    return out

ks=list(kugeln(16)); idx=SA.node_index(ks)
formen={s:SA.form(g,s) for s in ks}
haeufigkeit=Counter(formen.values())
print(f"{len(ks)} Kugeln, {len(haeufigkeit)} Quellformen")
for thr in (1,2,5,20):
    gute={f for f,c in haeufigkeit.items() if c>=thr}
    idxs=[i for i,s in enumerate(ks) if formen[s] in gute]
    behalten=set(idxs)
    paare=0; unionen={}
    for i in idxs:
        for j in SA.touching(g,ks,idx,i,nb):
            if i>=j or j not in behalten: continue
            paare+=1
            u=frozenset(ks[i]|ks[j])
            if u not in unionen: unionen[u]=None
    t0=time.time()
    for u in unionen: unionen[u]=SA.form(g,u)
    dt=time.time()-t0
    vh=Counter(unionen.values())
    selten=sum(1 for c in vh.values() if c==1)
    print(f"  Quellschwelle {thr:>2}: {len(gute):>2} Formen / {len(idxs):>3} Kugeln | "
          f"Paare {paare:>6,} | Vereinigungen {len(unionen):>6,} | Verbundformen {len(vh):>4} "
          f"(davon 1x: {selten:>3}) | form() {dt:5.1f}s")
