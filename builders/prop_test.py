"""
Property test suite for all arithmetic rule builders.
Tests compiled schema in isolation — no real-graph matching.

Properties tested per rule:

STRUCTURAL PROPERTIES (schema-level, independent of encoding):
  S1. Every output node is either inherited or born.
  S2. Every internal edge endpoint is an output node.
  S3. No self-loops in internal edges (spine nodes are not leaves).
  S4. Buffer is an output node (not deleted).

SPINE LENGTH (schema-level):
  L1. add_init output: exactly 1 spine node (out_result_spine). Length in = 0, out = 1.
  L2. bitadd coincident output: exactly 2 spine nodes (lsb + new_spine). Length in = 1, out = 2 (+1).
  L3. bitadd 2bit output: exactly 3 spine nodes (lsb + msb + new_spine). Length in = 2, out = 3 (+1).
  L4. bitadd multibit output: lsb + msb + new_spine, same +1. Length in = 3+, out = 3+ (+1, but msb is same).
  L5. finalise: output spine length = input spine length (no new nodes added, just consumed+rewired).

SPINE DIRECTION (schema-level):
  D1. S-chain goes lsb -> ... -> buffer (buffer has no S-out in internal edges).
  D2. out_result_spine is not the buffer endpoint.
  D3. For 2bit/multibit: internal S-chain is lsb->msb (2bit), or lsb has (S,out) crossing, msb has (S,in) crossing (multibit).

BIT VALUES (schema-level):
  B1. add_init: out_result_spine leaf self-loop iff result_bit = (lb+rb)%2 == 1.
  B2. bitadd: new spine node's leaf self-loop iff result_bit = (lb+rb+ci)%2 == 1.
  B3. out_result_spine self-loop = False (spine node is not a leaf).

CARRY (schema-level):
  C1. carry nodes present iff carry_out = (lb+rb(+ci)) >= 2.
  C2. carry forms a 2-cycle (S-edges: a->b, b->a).
  C3. carry attaches to the correct target: frontier of the result spine.

BUFFER CONNECTIONS (schema-level):
  BUF1. out_result_spine has OP-out to buffer (readback anchor).
  BUF2. out_handle has S-out to buffer.
  BUF3. Buffer has no internal S-out (it is a sink).

BOUNDARY CROSSINGS (schema-level):
  X1. out_result_spine has exactly 1 (OP,out) boundary crossing (bit pointer).
  X2. For multibit input: in_result_spine has (S,out) crossing declared.
  X3. For multibit input: in_result_msb has (S,in) crossing declared.
  X4. finalise lsb: (S,out) boundary crossing present (chain preserved externally).
  X5. finalise msb: (S,in) boundary crossing present.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(__file__) + '/../')
from basic_machinery.graph import EdgeType, Node, Edge, PerspectiveGraph
from basic_machinery.schema import compile_schema
from basic_machinery import encoding as E
from basic_machinery.operations import OperationDefinition
import spine_addinit_v4 as _ai
import spine_bitadd_v2 as _ba
import spine_finalise_v1 as _f1
import spine_finalise_multibit as _fmb

S = EdgeType.STRUCTURAL
O = EdgeType.OPERATIONAL
_STATES = ('single', 'term', 'cont')
_RW = ('coincident', '2bit', 'multibit')

# ── helpers ──────────────────────────────────────────────────────────────────

def s_outs(n, sc):  return [t for src,t,et in sc.edits.internal_edges if src==n and et==S]
def o_outs(n, sc):  return [t for src,t,et in sc.edits.internal_edges if src==n and et==O]
def s_ins(n, sc):   return [s for s,t,et in sc.edits.internal_edges if t==n and et==S]
def bg(n, sc):      return sc.edits.boundary_grab.get(n, set())
def has_bg(n,sc,et,dr): return any(e==et and d==dr for _,e,d in bg(n,sc))
def selfS(n, g2):   return Edge(n, n, S) in g2
def out_nodes(sc):  return set(sc.edits.inherit.keys()) | set(sc.edits.born)

def find(labels, name):
    return [Node(id=k) for k,v in labels.items() if v == name]

def find1(labels, name):
    ns = find(labels, name)
    return ns[0] if ns else None

# ── per-rule property checker ─────────────────────────────────────────────────

def check_rule(name, rule, labels, result_bit, carry_out, in_rw=None, is_finalise=False):
    sc = compile_schema(rule.graph2)
    g2 = rule.graph2
    out = out_nodes(sc)
    fails = []

    def F(prop, msg):
        fails.append(f"{prop}: {msg}")

    for n in out:
        if n not in sc.edits.inherit and n not in sc.edits.born:
            F("S1", f"output node n{n.id} neither inherited nor born")

    for src,tgt,et in sc.edits.internal_edges:
        if src not in out: F("S2", f"internal edge src n{src.id} not an output node")
        if tgt not in out: F("S2", f"internal edge tgt n{tgt.id} not an output node")

    buf = find1(labels, 'out_buffer')
    if buf and buf not in out: F("S4", "out_buffer not in output nodes")

    rsp = find1(labels, 'out_result_spine')
    rmsb = find1(labels, 'out_result_msb')
    newsp = find1(labels, 'out_new_spine')
    newlf = find1(labels, 'out_new_leaf')
    handle = find1(labels, 'out_handle')

    for sp in [rsp, rmsb, newsp]:
        if sp and any(src==sp and tgt==sp and et==S for src,tgt,et in sc.edits.internal_edges):
            F("S3", f"spine node n{sp.id} has internal S self-loop")

    if is_finalise:
        lsb = find1(labels, 'out_result_spine(lsb)')
        msb = find1(labels, 'out_result_spine(msb)')
        if lsb and not has_bg(lsb, sc, S, 'out'):
            F("X4", "finalise lsb missing (S,out) boundary crossing")
        if msb and not has_bg(msb, sc, S, 'in'):
            F("X5", "finalise msb missing (S,in) boundary crossing")
        return fails

    if rsp is None:
        F("MISSING", "no out_result_spine found"); return fails

    if buf and buf not in o_outs(rsp, sc):
        F("BUF1", f"out_result_spine missing OP-out to buffer; has {[n.id for n in o_outs(rsp,sc)]}")

    if handle and buf and buf not in s_outs(handle, sc):
        F("BUF2", f"out_handle missing S-out to buffer; has {[n.id for n in s_outs(handle,sc)]}")

    if buf and s_outs(buf, sc):
        F("BUF3", f"buffer has internal S-outs to {[n.id for n in s_outs(buf,sc)]}")

    n_op_cross = sum(1 for _,e,d in bg(rsp,sc) if e==O and d=='out')
    if n_op_cross != 1:
        F("X1", f"out_result_spine has {n_op_cross} (OP,out) crossings, expected 1")

    if in_rw is None:
        if rmsb is not None: F("L1", "add_init has out_result_msb (expected none)")
        if newsp is not None: F("L1", "add_init has out_new_spine (expected none)")
        leaf_candidates = [t for t in o_outs(rsp,sc) if buf and t!=buf]
        if leaf_candidates:
            lf = leaf_candidates[0]
            if selfS(lf,g2) != (result_bit==1):
                F("B1", f"leaf selfS={selfS(lf,g2)}, expected result_bit={result_bit}")
        if selfS(rsp,g2): F("B3", "out_result_spine has structural self-loop")
        ca = find1(labels, 'out_carry_a'); cb = find1(labels, 'out_carry_b')
        has_carry = ca is not None
        if has_carry != carry_out:
            F("C1", f"carry_out={carry_out} but carry_nodes={'present' if has_carry else 'absent'}")
        if has_carry and ca and cb:
            if cb not in s_outs(ca,sc) or ca not in s_outs(cb,sc):
                F("C2", "carry 2-cycle broken in internal edges")

    elif in_rw == 'coincident':
        rmsb_c = find1(labels, 'out_new_spine')
        if rmsb_c is None: F("L2", "coincident missing out_new_spine")
        if find1(labels, 'out_result_msb') is not None: F("L2", "coincident unexpected out_result_msb")
        rmsb = rmsb_c
        if rmsb:
            if rmsb not in s_outs(rsp, sc): F("D1", "rsp not S-> out_new_spine")
            if buf and buf not in s_outs(rmsb, sc): F("D1", "out_new_spine not S-> buffer")
            newlf_c = find1(labels, 'out_new_leaf')
            if newlf_c:
                if selfS(newlf_c,g2) != (result_bit==1):
                    F("B2", f"coincident new_leaf selfS={selfS(newlf_c,g2)}, expected result_bit={result_bit}")
            if selfS(rmsb,g2): F("B3", "out_new_spine has structural self-loop")
        ca = find1(labels, 'out_carry_a'); cb = find1(labels, 'out_carry_b')
        if (ca is not None) != carry_out:
            F("C1", f"carry_out={carry_out} but carry={'present' if ca else 'absent'}")
        if ca and cb and (cb not in s_outs(ca,sc) or ca not in s_outs(cb,sc)):
            F("C2", "carry 2-cycle broken")
        if ca and rmsb and rmsb not in s_outs(ca,sc):
            F("C3", f"carry_a S-outs={[n.id for n in s_outs(ca,sc)]}, new_spine={rmsb.id} missing")

    elif in_rw == '2bit':
        if rmsb is None: F("L3", "2bit missing out_result_msb")
        if newsp is None: F("L3", "2bit missing out_new_spine")
        if rmsb and newsp:
            if rmsb not in s_outs(rsp, sc): F("D1-2b", "rsp not S-> rmsb")
            if newsp not in s_outs(rmsb, sc): F("D1-2b", "rmsb not S-> newsp")
            if buf and buf not in s_outs(newsp, sc): F("D1-2b", "newsp not S-> buffer")
            if newlf:
                if selfS(newlf,g2) != (result_bit==1):
                    F("B2", f"2bit newlf selfS={selfS(newlf,g2)}, expected result_bit={result_bit}")
            for sp in [rmsb, newsp]:
                if selfS(sp,g2): F("B3", f"spine node n{sp.id} has structural self-loop")
        ca = find1(labels, 'out_carry_a'); cb = find1(labels, 'out_carry_b')
        if (ca is not None) != carry_out:
            F("C1", f"carry_out={carry_out} carry={'present' if ca else 'absent'}")
        if ca and cb and (cb not in s_outs(ca,sc) or ca not in s_outs(cb,sc)):
            F("C2", "carry 2-cycle broken")
        if ca and newsp and newsp not in s_outs(ca,sc):
            F("C3", f"carry_a not S-> newsp; has {[n.id for n in s_outs(ca,sc)]}")
        if has_bg(rsp, sc, S, 'out'):
            F("X2", "2bit rsp has (S,out) crossing — should be internal for 2bit")

    elif in_rw == 'multibit':
        if rmsb is None: F("L4", "multibit missing out_result_msb")
        if newsp is None: F("L4", "multibit missing out_new_spine")
        if rmsb and newsp:
            if rmsb in s_outs(rsp, sc):
                F("D3", "multibit rsp has internal S-out to rmsb — should be crossing")
            if not has_bg(rsp, sc, S, 'out'):
                F("X2", "multibit rsp missing (S,out) crossing")
            if not has_bg(rmsb, sc, S, 'in'):
                F("X3", "multibit rmsb missing (S,in) crossing")
            if newsp not in s_outs(rmsb, sc): F("D1-mb", "rmsb not S-> newsp")
            if buf and buf not in s_outs(newsp, sc): F("D1-mb", "newsp not S-> buffer")
            if newlf:
                if selfS(newlf,g2) != (result_bit==1):
                    F("B2", f"multibit newlf selfS={selfS(newlf,g2)}, expected result_bit={result_bit}")
        ca = find1(labels, 'out_carry_a'); cb = find1(labels, 'out_carry_b')
        if (ca is not None) != carry_out:
            F("C1", f"carry_out={carry_out} carry={'present' if ca else 'absent'}")
        if ca and cb and (cb not in s_outs(ca,sc) or ca not in s_outs(cb,sc)):
            F("C2", "carry 2-cycle broken")
        if ca and newsp and newsp not in s_outs(ca,sc):
            F("C3", f"carry_a not S-> newsp; has {[n.id for n in s_outs(ca,sc)]}")

    return fails


# ── main ──────────────────────────────────────────────────────────────────────

all_results = {}

for lb in (0,1):
    for rb in (0,1):
        for ls in _STATES:
            for rs in _STATES:
                name = f"add_init({lb},{rb},{ls},{rs})"
                rule, labels = _ai.build_labeled(lb, rb, ls, rs)
                rb_bit = (lb+rb)%2; carry = (lb+rb)>=2
                fails = check_rule(name, rule, labels, rb_bit, carry, in_rw=None)
                all_results[name] = fails

for rw in _RW:
    for lb in (0,1):
        for rb in (0,1):
            for ci in (0,1):
                if lb==0 and rb==0 and ci==0: continue
                for ls in _STATES:
                    for rs in _STATES:
                        name = f"ba({lb},{rb},c{ci},{ls},{rs},{rw})"
                        try:
                            rule, labels = _ba.build_labeled(lb, rb, ci, ls, rs, rw)
                        except Exception as e:
                            all_results[name] = [f"BUILD_ERROR: {e}"]; continue
                        rb_bit = (lb+rb+ci)%2; carry = (lb+rb+ci)>=2
                        fails = check_rule(name, rule, labels, rb_bit, carry, in_rw=rw)
                        all_results[name] = fails

rule, labels = _f1.build_finalise()
all_results['finalise_v1'] = check_rule('finalise_v1', rule, labels, 0, False, is_finalise=True)

rule, labels = _fmb.build_finalise_multibit()
all_results['finalise_multibit'] = check_rule('finalise_multibit', rule, labels, 0, False, is_finalise=True)

total = len(all_results)
failed = {k:v for k,v in all_results.items() if v}
passed = total - len(failed)

print(f"Property test: {passed}/{total} rules PASS\n")

if failed:
    by_prop = {}
    for rule_name, fs in failed.items():
        for f in fs:
            prop = f.split(':')[0].strip()
            by_prop.setdefault(prop, []).append(f"{rule_name} — {f}")
    print(f"=== {len(failed)} rules with failures ===\n")
    for prop in sorted(by_prop):
        print(f"[{prop}] ({len(by_prop[prop])} instances)")
        for line in by_prop[prop][:4]: print(f"  {line}")
        if len(by_prop[prop])>4: print(f"  ... +{len(by_prop[prop])-4} more")
        print()
else:
    print("ALL RULES PASS ALL PROPERTIES")
