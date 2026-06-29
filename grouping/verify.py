"""
verify.py — drive real reductions and assert grouped_dispatch == flat_baseline
at every step across a set of expressions.
"""
import basic_machinery.operations as ops
import basic_machinery.arithmetic_spine as _spine
if not ops._registry:
    _spine.register_all()

from basic_machinery.encoding import encode
from basic_machinery.graph import PerspectiveGraph, EdgeType
from basic_machinery.operations import apply
from dispatch import build_dispatch_tree, flat_baseline, grouped_dispatch

bit_add_names = sorted(n for n in ops._registry if n.startswith('bit_add'))
tree = build_dispatch_tree(bit_add_names)
print("dispatch tree root members:", len(tree.members), "rules")

ALL = list(ops._registry.keys())

def fresh(expr):
    g = PerspectiveGraph(); encode(g, expr); return g

def step_any(g):
    for nm in ALL:
        snap = g.copy()
        if apply(g, ops._registry[nm]):
            return nm
        g.restore(snap)
    return None

mismatches = 0
checks = 0
for expr in ["1+1", "2+3", "3+5", "6+7", "5+6", "7+7", "4+1", "2+2"]:
    g = fresh(expr)
    for _ in range(12):
        flat = flat_baseline(g, bit_add_names)
        grp  = grouped_dispatch(g, tree)
        if flat != grp:
            mismatches += 1
            print(f"  MISMATCH [{expr}] flat={flat} grouped={grp}")
        checks += 1
        fired = step_any(g)
        if fired is None:
            break

print(f"\nchecks={checks} mismatches={mismatches}")
print("EQUIVALENT" if mismatches == 0 else "NOT EQUIVALENT")
