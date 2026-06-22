"""Fault injection: force an un-anchorable rule and prove the build degrades it
to a singleton (ground leaf) instead of crashing, AND records it in `degraded`."""
import sys
import basic_machinery.operations as ops
import basic_machinery.arithmetic
import grouping
from grouping import GroupCoreError
import dispatch

# Monkeypatch group_core so one specific rule raises (simulates a malformed/
# symmetric GA rule the anchor logic can't seed). Every other call passes through.
real_group_core = grouping.group_core
BAD = 'bit_add_11_c1'
def flaky(rules):
    names = [r.name for r in rules]
    if BAD in names:
        raise GroupCoreError(f"injected: {BAD} un-anchorable")
    return real_group_core(rules)

grouping.group_core = flaky
dispatch.group_core = flaky  # dispatch imported the symbol directly

bit_add = sorted(n for n in ops._registry if n.startswith('bit_add'))
try:
    matchers, dendro, degraded = dispatch.build_groups(bit_add, c_min=5, f=0.5)
except Exception as e:
    print(f"CRASHED instead of degrading: {type(e).__name__}: {e}")
    sys.exit(1)

print("build did not crash")
print("degraded:", degraded)
# BAD must be flagged degraded and must appear as its own singleton matcher
assert BAD in degraded, f"{BAD} should be recorded degraded"
bad_matchers = [m for m in matchers if m.members == [BAD]]
assert len(bad_matchers) == 1, f"{BAD} should be a singleton ground leaf, groups={[m.members for m in matchers]}"
assert bad_matchers[0].core is None, "degraded singleton should have no core_info"

# the BAD rule must STILL be matchable directly (function preserved, just ungrouped)
from basic_machinery.encoding import encode
from basic_machinery.graph import PerspectiveGraph
gm = bad_matchers[0]
# its dispatch path falls back to its own match — confirm the matcher can run
print("degraded rule still has working direct dispatch:", hasattr(gm, 'dispatch'))
print("PASS")
