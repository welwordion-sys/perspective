"""Wann ist Korrelation billiger als Budgetverdopplung?
Beide erreichen Strukturen bis Groesse 2k. Gemessen ueber Graphfamilien.
"""
import os, sys, time, random, signal
R='/home/claude/repo'
for p in ['','GA','grouping','builders','basic_machinery']: sys.path.insert(0,os.path.join(R,p))
from basic_machinery.graph import PerspectiveGraph, EdgeType
import structure_analysis as SA
S=EdgeType.STRUCTURAL; O=EdgeType.OPERATIONAL

def kette(n):
    g=PerspectiveGraph(); ns=[g.add_node() for _ in range(n)]
    for i in range(n-1): g.add_edge(ns[i],ns[i+1],S)
    return g
def baum(n):
    g=PerspectiveGraph(); ns=[g.add_node() for _ in range(n)]
    for i in range(1,n): g.add_edge(ns[(i-1)//2],ns[i],S)
    return g
def gitter(w,h):
    g=PerspectiveGraph(); nd={}
    for y in range(h):
        for x in range(w): nd[(x,y)]=g.add_node()
    for y in range(h):
        for x in range(w):
            if x+1<w: g.add_edge(nd[(x,y)],nd[(x+1,y)],S)
            if y+1<h: g.add_edge(nd[(x,y)],nd[(x,y+1)],S)
    return g
def zufall(n,m,seed):
    rng=random.Random(seed); g=PerspectiveGraph(); ns=[g.add_node() for _ in range(n)]
    for i in range(1,n): g.add_edge(ns[rng.randrange(i)],ns[i],S)   # zusammenhaengend
    da=set()
    versuche=0
    while len(g.edges)<m and versuche<5000:
        versuche+=1
        a,b=rng.sample(ns,2); t=rng.choice([S,O])
        if (a,b,t) in da: continue
        try: g.add_edge(a,b,t); da.add((a,b,t))
        except ValueError: pass
    return g
def spine(bits,l,r):
    g=PerspectiveGraph(); ring=[g.add_node() for _ in range(4)]
    for i in range(4): g.add_edge(ring[i],ring[(i+1)%4],S)
    a=g.add_node(); g.add_edge(ring[0],a,S)
    for port,val in ((0,l),(1,r)):
        prev=None
        for i in range(bits):
            s=g.add_node(); lf=g.add_node(); g.add_edge(s,lf,O)
            if (val>>i)&1: g.add_edge(lf,lf,S)
            g.add_edge(prev,s,S) if prev else g.add_edge(ring[port],s,O)
            prev=s
    return g

class TO(Exception): pass
signal.signal(signal.SIGALRM, lambda s,f:(_ for _ in ()).throw(TO()))
B=3
print(f"{'Graph':<22} {'n':>4} {'m':>4} {'Dichte':>7} | {'k=3 max_k':>9} {'Korrel.':>9} {'t_korr':>8} | "
      f"{'k=6 alle':>10} {'t_budget':>9} | Faktor")
for name,g in [("Kette n=20",kette(20)), ("Binaerbaum n=31",baum(31)),
               ("Spine 4bit",spine(4,5,3)), ("Gitter 5x5",gitter(5,5)),
               
               ("Zufall n=25 m=30",zufall(25,30,1)), ("Zufall n=25 m=50",zufall(25,50,2)),
               ("Zufall n=20 m=60",zufall(20,60,3))]:
    n,m=len(g.nodes),len(g.edges); d=2*m/n
    t0=time.time(); _,mk=SA.find_structures(g,B); c=SA.correlate(g,mk,0.0); t_k=time.time()-t0
    signal.alarm(45); t0=time.time()
    try:
        allg2,_=SA.find_structures(g,2*B); t_b=time.time()-t0; signal.alarm(0)
        anz=f"{len(allg2):,}"; fak=f"{t_b/max(t_k,1e-6):6.1f}x"
    except TO:
        signal.alarm(0); anz=">45s"; t_b=float('inf'); fak="  >>"
    print(f"{name:<22} {n:>4} {m:>4} {d:>7.1f} | {len(mk):>9,} {len(c):>9,} {t_k:>7.2f}s | "
          f"{anz:>10} {(f'{t_b:7.2f}s' if t_b!=float('inf') else '   ---'):>9} | {fak}")
