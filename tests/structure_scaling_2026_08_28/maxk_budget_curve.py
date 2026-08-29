import os, sys, time, signal
R='/home/claude/repo'
for p in ['','GA','grouping','builders','basic_machinery']: sys.path.insert(0,os.path.join(R,p))
from basic_machinery.graph import PerspectiveGraph, EdgeType
import structure_analysis as SA

def grid(w,h,tags=True):
    g=PerspectiveGraph(); node={}
    for y in range(h):
        for x in range(w): node[(x,y)]=g.add_node()
    for y in range(h):
        for x in range(w):
            if x+1<w: g.add_edge(node[(x,y)],node[(x+1,y)],EdgeType.STRUCTURAL)
            if y+1<h: g.add_edge(node[(x,y)],node[(x,y+1)],EdgeType.STRUCTURAL)
    if tags:
        for n in list(node.values()):
            t=g.add_node(); g.add_edge(n,t,EdgeType.STRUCTURAL)
    return g

class TO(Exception): pass
signal.signal(signal.SIGALRM, lambda s,f: (_ for _ in ()).throw(TO()))

for (w,h) in [(3,3),(4,4)]:
    g=grid(w,h)
    print(f"--- {w}x{h}: {len(g.nodes)} Knoten, {len(g.edges)} Kanten "
          f"(Gesamtkanten = Obergrenze fuer Budget) ---")
    print(f"{'Budget':>7} {'alle':>12} {'max_k':>10} {'Zeit':>8}")
    for b in range(1, len(g.edges)+2):
        signal.alarm(90); t0=time.time()
        try:
            allg,mk=SA.find_structures(g,b); signal.alarm(0)
            print(f"{b:>7} {len(allg):>12,} {len(mk):>10,} {time.time()-t0:>7.2f}s")
            if len(mk)==1: print("        -> max_k auf 1 gefallen"); break
        except TO:
            signal.alarm(0); print(f"{b:>7} {'ABBRUCH >90s':>12}"); break
