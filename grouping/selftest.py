"""One-shot self-test: rebuild groups and assert equivalence. Exit 1 on failure."""
import sys
import basic_machinery.operations as ops
import basic_machinery.arithmetic
from basic_machinery.encoding import encode
from basic_machinery.graph import PerspectiveGraph
from basic_machinery.operations import apply
from dispatch import build_groups, flat_baseline, grouped_dispatch

bit_add = sorted(n for n in ops._registry if n.startswith('bit_add'))
matchers, _, degraded = build_groups(bit_add, c_min=5, f=0.5)
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
for expr in ["1+1","2+3","3+5","6+7","5+6","7+7","4+1","2+2"]:
    g = fresh(expr)
    for _ in range(12):
        if flat_baseline(g, bit_add) != grouped_dispatch(g, matchers): mm += 1
        chk += 1
        if step(g) is None: break
groups = [sorted(m.members) for m in matchers]
assert len(matchers) == 2, f"expected 2 groups, got {len(matchers)}"
assert degraded == [], f"well-formed bit_add should degrade nothing, got {degraded}"
print(f"groups={groups}")
print(f"checks={chk} mismatches={mm}")
if mm: print("FAIL"); sys.exit(1)
print("PASS")
