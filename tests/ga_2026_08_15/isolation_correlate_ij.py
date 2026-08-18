"""Abschalt-Test 2: ist `if i>=j: continue` die Ursache?
Hypothese: der Filter sollte a+b/b+a entdoppeln, entfernt aber die HALBE
gerichtete Korrelation — welche Haelfte, entscheidet die Indexvergabe.
Falsifikator: ohne Filter muss (1) die Zahl deterministisch UND (2) die
Asymmetrie unabhaengig von der Indexvergabe sein.
"""
import os, sys
_R = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in ["", "ga", "grouping", "builders", "basic_machinery"]:
    _q = os.path.join(_R, _p)
    if _q not in sys.path:
        sys.path.insert(0, _q)

import os
_d=os.path.dirname(os.path.abspath(__file__))
import math, random
from collections import defaultdict
import structure_analysis as N
from basic_machinery.graph import PerspectiveGraph, EdgeType

def spine(bits,lval,rval):
    g=PerspectiveGraph(); ring=[g.add_node() for _ in range(4)]
    for i in range(4): g.add_edge(ring[i],ring[(i+1)%4],EdgeType.STRUCTURAL)
    a=g.add_node(); g.add_edge(ring[0],a,EdgeType.STRUCTURAL)
    for port,val in ((0,lval),(1,rval)):
        prev=None
        for i in range(bits):
            s=g.add_node(); leaf=g.add_node()
            g.add_edge(s,leaf,EdgeType.OPERATIONAL)
            if (val>>i)&1: g.add_edge(leaf,leaf,EdgeType.STRUCTURAL)
            if prev: g.add_edge(prev,s,EdgeType.STRUCTURAL)
            else: g.add_edge(ring[port],s,EdgeType.OPERATIONAL)
            prev=s
    return g

def correlate(g, max_k, min_share=0.02, use_ij=True, shuffle_seed=None):
    max_k=list(max_k)
    if shuffle_seed is not None:
        random.Random(shuffle_seed).shuffle(max_k)   # Indexvergabe variieren
    nb=N.undirected_adjacency(g); idx=N.node_index(max_k)
    by_form=N.group_by_form(g,max_k); pos={s:i for i,s in enumerate(max_k)}
    thr=max(1,math.ceil(len(max_k)*min_share))
    out=[]
    for A,occs in by_form.items():
        if len(occs)<thr: continue
        hits=defaultdict(set); zones=defaultdict(list)
        for k,o in enumerate(occs):
            i=pos[o]
            for j in N.touching(g,max_k,idx,i,nb):
                if use_ij and i>=j: continue
                p=max_k[j]; f=N.form(g,frozenset(o|p))
                hits[f].add(k); zones[f].append(len(set(p)-set(o)))
        for f,ks in hits.items():
            out.append((A,f,len(ks)/len(occs)))
    return out

def asym(cors):
    d=defaultdict(list)
    for _,j,c in cors: d[j].append(c)
    return len([1 for v in d.values() if len(v)>=2 and max(v)-min(v)>0.3])

g=spine(4,5,3); _,mk=N.find_structures(g,4)
for seed in (None,1,2,3,4):
    a=correlate(g,mk,use_ij=True, shuffle_seed=seed)
    b=correlate(g,mk,use_ij=False,shuffle_seed=seed)
    print("Indexvergabe %-4s | MIT i<j: %3d Korr / %2d asym | OHNE: %3d Korr / %2d asym"
          % (seed, len(a), asym(a), len(b), asym(b)))
