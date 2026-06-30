"""One-shot self-test: build dispatch tree and assert equivalence on FIRING states.

CRITICAL: encode with =result form (e.g. '1+1=2'), NOT bare '1+1'. Without the
expected-result term no rule fires and the test is vacuous (None==None). The test
asserts fires>0 to guard against this regression.
"""
import sys
import basic_machinery.operations as ops
import builders.arithmetic_spine as _spine
if 'bit_add_00_c0_cont_cont_2bit' not in ops._registry:
    _spine.register_all()

from basic_machinery.encoding import encode
from basic_machinery.graph import PerspectiveGraph
from basic_machinery.operations import apply, snapshot, revert
from dispatch import build_dispatch_tree, flat_baseline, grouped_dispatch

# add_init rules fire on freshly-encoded a+b=c states
add_init = sorted(n for n in ops._registry if n.startswith('add_init'))
tree = build_dispatch_tree(add_init)
ALL = list(ops._registry.keys())

def fresh(e):
    g = PerspectiveGraph(); encode(g, e); return g

mm = chk = fires = 0
for a in range(4):
    for b in range(4):
        expr = f'{a}+{b}={a+b}'
        gf = fresh(expr)
        gg = fresh(expr)
        flat = flat_baseline(gf, add_init)
        grp  = grouped_dispatch(gg, tree)
        if flat != grp:
            mm += 1
            print(f"  MISMATCH [{expr}] flat={flat} grouped={grp}")
        if flat is not None:
            fires += 1
        chk += 1

print(f"add_init rules={len(add_init)}")
print(f"checks={chk} fires={fires} mismatches={mm}")
if fires == 0:
    print("VACUOUS — no rule fired, test proves nothing"); sys.exit(1)
if mm:
    print("FAIL"); sys.exit(1)
print("PASS")
