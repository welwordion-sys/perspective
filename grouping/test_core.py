"""
test_core.py — validity tests for core_finder, core_tree, delta_extractor.

Gates:
  1. self_match:  find_core(A, A) -> all edges safe
  2. relabel:     find_core(A, relabeled_A) -> all edges safe
  3. synthetic_disconnected: two disconnected regions found, delta excluded
  4. synthetic_expanding: shared core with different arms
  5. carrier_pairwise: tt vs mres=60, tt vs mop=61
  6. core_tree: 3-way tree structure correct
  7. delta: core + delta = full variant
"""
import sys
sys.path.insert(0, '/tmp')

from core_finder import find_core
from core_tree import build_tree, print_tree
from delta_extractor import extract_delta
from carriers import CARRIERS

PASS = FAIL = 0

def check(label, cond, detail=''):
    global PASS, FAIL
    if cond: print(f'  PASS  {label}'); PASS += 1
    else:    print(f'  FAIL  {label}  {detail}'); FAIL += 1

def norm(e):    return (e[0],e[1],e[2],e[3])
def relabel(es, off): return [(s+off,t+off,k,ty) for s,t,k,ty in es]

tt   = list(map(norm, CARRIERS['core_tt_2bit']))
mres = relabel(list(map(norm, CARRIERS['core_mres_multibit'])),1000)
mop  = relabel(list(map(norm, CARRIERS['core_mop_multibit'])),2000)
tt_r = relabel(tt, 1000)

print('Gate 1: self-match')
r = find_core(tt, tt)
check('tt self-match', len(r['safe_core'])==len(tt), f"{len(r['safe_core'])}/{len(tt)}")

print('Gate 2: relabel')
r = find_core(tt, tt_r)
check('tt relabel', len(r['safe_core'])==len(tt), f"{len(r['safe_core'])}/{len(tt)}")

print('Gate 3: disconnected regions')
A1=[(0,1,'s',None),(1,2,'s',None),(3,4,'s',None),(4,3,'s',None),(5,0,'s',None)]
B1=[(10,11,'s',None),(11,12,'s',None),(13,14,'s',None),(14,13,'s',None),(15,12,'o',None)]
r = find_core(A1, B1)
check('disconnected: best=4',      len(r['safe_core'])==4, f"{len(r['safe_core'])}")
check('disconnected: A-only excluded', (5,0,'s',None) not in r['safe_core'])
check('disconnected: 2 subgraphs', len(r['subgraphs'])==2, f"{len(r['subgraphs'])}")

print('Gate 4: expanding arms')
A2=[(0,1,'s',None),(1,2,'s',None),(2,0,'s',None),(0,3,'s',None),(3,4,'s',None)]
B2=[(10,11,'s',None),(11,12,'s',None),(12,10,'s',None),(13,10,'s',None),(14,13,'s',None)]
r = find_core(A2, B2)
check('expanding: best=4', len(r['safe_core'])==4, f"{len(r['safe_core'])}")

print('Gate 5: carrier pairwise')
r = find_core(tt, mres)
check('tt vs mres: 60', len(r['safe_core'])==60, f"{len(r['safe_core'])}")
r = find_core(tt, mop)
check('tt vs mop: 61',  len(r['safe_core'])==61, f"{len(r['safe_core'])}")

print('Gate 6: core tree')
graphs = {'tt': tt, 'mres': mres, 'mop': mop}
tree = build_tree(graphs)
check('tree root has 3 members', len(tree.members)==3)
check('tree root core=60', tree.size==60, f"{tree.size}")
check('tree has children', len(tree.children)>0)

print('Gate 7: delta')
r = find_core(tt, mres)
_, node_map = r['subgraphs'][0]
delta = extract_delta(r['safe_core'], node_map, mres)
core_in_v = {(node_map[e[0]], node_map[e[1]], e[2], e[3]) for e in r['safe_core']}
check('mres delta: core+delta=variant',
      len(core_in_v)+delta.total_steps()==len(mres),
      f"{len(core_in_v)}+{delta.total_steps()}={len(mres)}")
check('mres delta: 7 new edges', len(delta.new_edges)==7, f"{len(delta.new_edges)}")
check('mres delta: 0 new nodes', len(delta.new_nodes)==0, f"{len(delta.new_nodes)}")

r = find_core(tt, mop)
_, node_map = r['subgraphs'][0]
delta = extract_delta(r['safe_core'], node_map, mop)
core_in_v = {(node_map[e[0]], node_map[e[1]], e[2], e[3]) for e in r['safe_core']}
check('mop delta: core+delta=variant',
      len(core_in_v)+delta.total_steps()==len(mop),
      f"{len(core_in_v)}+{delta.total_steps()}={len(mop)}")

print(f'\n{PASS} passed, {FAIL} failed')
sys.exit(0 if FAIL==0 else 1)
