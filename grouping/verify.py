import basic_machinery.operations as ops
import basic_machinery.arithmetic
from basic_machinery.encoding import build_number, build_operator, connect_operands
from basic_machinery.graph import PerspectiveGraph, EdgeType
from dispatch import build_groups, flat_baseline, grouped_dispatch
from basic_machinery.operations import apply

bit_add_names = sorted(n for n in ops._registry if n.startswith('bit_add'))
matchers, dendro, degraded = build_groups(bit_add_names, c_min=5, f=0.5)
print("groups:", [sorted(m.members) for m in matchers])

# Generate real graph states by encoding additions and driving them through
# add_init then bit_add steps, capturing the live graph at each point. Then at
# each captured state, compare flat_baseline vs grouped_dispatch.
def fresh(expr):
    from basic_machinery.encoding import encode
    g = PerspectiveGraph(); encode(g, expr); return g

ALL = list(ops._registry.keys())
def step_any(g):
    # apply the first applicable rule in registry order (the real engine behavior)
    for nm in ALL:
        snap = g.copy()
        if apply(g, ops._registry[nm]):
            return nm
        g.restore(snap)
    return None

mismatches = 0
checks = 0
for expr in ["1+1","2+3","3+5","6+7","5+6","7+7","4+1","2+2"]:
    g = fresh(expr)
    for _ in range(12):
        # compare dispatch decisions on bit_add group at THIS state
        flat = flat_baseline(g, bit_add_names)
        grp  = grouped_dispatch(g, matchers)
        if flat != grp:
            mismatches += 1
            print(f"  MISMATCH [{expr}] flat={flat} grouped={grp}")
        checks += 1
        fired = step_any(g)
        if fired is None:
            break

print(f"\nchecks={checks} mismatches={mismatches}")
print("EQUIVALENT" if mismatches==0 else "NOT EQUIVALENT")
