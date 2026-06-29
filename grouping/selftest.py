"""One-shot self-test: build dispatch tree and assert equivalence. Exit 1 on failure."""
import sys
import basic_machinery.operations as ops
import basic_machinery.arithmetic_spine as _spine
if not ops._registry:
    _spine.register_all()

from basic_machinery.encoding import encode
from basic_machinery.graph import PerspectiveGraph
from basic_machinery.operations import apply
from dispatch import build_dispatch_tree, flat_baseline, grouped_dispatch

bit_add = sorted(n for n in ops._registry if n.startswith('bit_add'))
tree = build_dispatch_tree(bit_add)
ALL = list(ops._registry.keys())

def fresh(e):
    g = PerspectiveGraph(); encode(g, e); return g

def step(g):
    for nm in ALL:
        s = g.copy()
        if apply(g, ops._registry[nm]): return nm
        g.restore(s)
    return None

mm = chk = 0
for expr in ["1+1", "2+3", "3+5", "6+7", "5+6", "7+7", "4+1", "2+2"]:
    g = fresh(expr)
    for _ in range(12):
        flat = flat_baseline(g, bit_add)
        grp  = grouped_dispatch(g, tree)
        if flat != grp:
            mm += 1
            print(f"  MISMATCH [{expr}] flat={flat} grouped={grp}")
        chk += 1
        if step(g) is None:
            break

print(f"groups={tree.members}")
print(f"checks={chk} mismatches={mm}")
if mm:
    print("FAIL"); sys.exit(1)
print("PASS")
