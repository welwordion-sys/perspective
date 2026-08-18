"""
decoder.py — topology-driven structural reader for PerspectiveGraph.

Independent verification instrument. Reads node ROLES live from edge topology
every time; never stores labels, never reuses ids across spaces, never calls the
matcher (so it cannot inherit a matcher bug it is meant to catch).

Vocabulary (from encoding.py, live encoder spine_encoding + operator_port_topology):
  bit value    : bit node has STRUCTURAL self-loop => 1, else 0
  spine vertex : node with an OP-out edge to its bit node, and optional S-out to
                 the next spine vertex (LSB -> MSB)
  number       : a spine chain; value read LSB-first by walking S-successors
  operator     : an anchored directed STRUCTURAL cycle of size k
                   k -> operator via _OPERATOR_TAGS (3 +, 4 -, 5 *, 6 /), 7 = '='
                 cycle[0] carries the anchor (dead-end S edge); ports cycle[0]/cycle[1];
                 handle = cycle[last]; tail (dead-end S off cycle[last]) iff unfinished
  parameter    : node with a bidirectional STRUCTURAL edge to a companion, no bit tree

Output: DecodeResult(expr, value, loose_nodes, anomalies, operators, numbers).
loose_nodes = nodes never consumed by any structural read = artifacts.
anomalies   = structural contradictions surfaced rather than guessed.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from basic_machinery.graph import PerspectiveGraph, Node, Edge, EdgeType

_OPERATOR_BY_SIZE = {3: '+', 4: '-', 5: '*', 6: '/', 7: '='}


@dataclass
class OperatorRead:
    cycle: list[Node]            # ordered cycle[0..k-1], oriented so [0] carries anchor
    op: str
    handle: Node                 # cycle[last]
    anchor: Node
    tail: Node | None            # None iff finished
    port0: Node                  # cycle[0] target via OP (left operand entry) or None
    port1: Node                  # cycle[1] target via OP (right operand entry) or None
    evidence: str = ''


@dataclass
class NumberRead:
    lsb: Node
    bits: list[int]              # LSB first
    value: int
    spine: list[Node]
    evidence: str = ''


@dataclass
class DecodeResult:
    expr: str | None = None
    value: int | None = None
    operators: list[OperatorRead] = field(default_factory=list)
    numbers: list[NumberRead] = field(default_factory=list)
    parameters: list[Node] = field(default_factory=list)
    loose_nodes: set[Node] = field(default_factory=set)
    anomalies: list[str] = field(default_factory=list)


def _s_out(g, n): return [e.target for e in g.edges_from(n, EdgeType.STRUCTURAL) if e.target != n]
def _s_in(g, n):  return [e.source for e in g.edges_to(n, EdgeType.STRUCTURAL) if e.source != n]
def _op_out(g, n):return [e.target for e in g.edges_from(n, EdgeType.OPERATIONAL) if e.target != n]
def _has_s_self(g, n): return Edge(n, n, EdgeType.STRUCTURAL) in g


def _find_structural_cycles(g: PerspectiveGraph) -> list[list[Node]]:
    """Find simple directed cycles over STRUCTURAL edges. Sizes here are tiny
    (3..7), so a bounded DFS per node is cheap. Returns each cycle once."""
    succ = {n: [e.target for e in g.edges_from(n, EdgeType.STRUCTURAL) if e.target != n]
            for n in g.nodes}
    found: list[list[Node]] = []
    seen_sets: list[frozenset] = []

    def dfs(start, current, path):
        for nxt in succ[current]:
            if nxt == start and len(path) >= 3:
                fs = frozenset(path)
                if fs not in seen_sets:
                    seen_sets.append(fs)
                    found.append(list(path))
                continue
            if nxt in path:
                continue
            if len(path) >= 7:
                continue
            path.append(nxt)
            dfs(start, nxt, path)
            path.pop()

    for n in g.nodes:
        dfs(n, n, [n])
    return found


def _orient_cycle(g: PerspectiveGraph, cycle_set: list[Node]) -> tuple[list[Node], Node, Node | None, str] | None:
    """
    Orient a structural cycle so index 0 is the anchored port (cycle[0]).
    Returns (ordered_cycle, anchor, tail_or_None, evidence) or None if it can't
    be oriented unambiguously (caller records an anomaly).

    Disambiguation (no circular use of 'anchor identifies [0]'):
      - cycle[0]   : a cycle member with a dead-end S-out (anchor) whose in-cycle
                     predecessor is cycle[last].
      - cycle[last]: the member with a dead-end S-out (tail, unfinished) OR, on a
                     finished operator, the unique predecessor of cycle[0].
      Finished: exactly one dead-end (anchor at [0]).
      Unfinished: two dead-ends (anchor at [0], tail at [last]); [last] is the
                  in-cycle predecessor of [0], and its dead-end is the tail.
    """
    members = set(cycle_set)
    # rebuild the ring order from the structural edges among members
    ring = [cycle_set[0]]
    while len(ring) < len(cycle_set):
        cur = ring[-1]
        nxts = [t for t in _s_out(g, cur) if t in members and t not in ring]
        if not nxts:
            # could be the closing edge back to ring[0]; ring done if so
            if ring[0] in _s_out(g, cur):
                break
            return None
        ring.append(nxts[0])

    # dead-end S-out targets (outside the ring) per member
    deadends = {}
    for m in ring:
        outs = [t for t in _s_out(g, m) if t not in members]
        deadends[m] = outs

    members_with_deadend = [m for m in ring if deadends[m]]

    if len(members_with_deadend) == 1:
        # finished: the lone dead-end is the anchor at cycle[0]
        c0 = members_with_deadend[0]
        anchor = deadends[c0][0]
        tail = None
        ev = f"finished: single dead-end (anchor={anchor.id}) at cycle0={c0.id}"
    elif len(members_with_deadend) == 2:
        # unfinished: anchor at [0], tail at [last]; [last] is in-ring predecessor of [0].
        a, b = members_with_deadend
        # predecessor in ring
        def pred(x): 
            i = ring.index(x); return ring[i - 1]
        # cycle[last] -> cycle[0] is a ring edge, so [0]'s predecessor is [last].
        # Identify which of a,b is [0]: the one whose ring-predecessor is the OTHER.
        if pred(a) == b:
            c0, clast = a, b
        elif pred(b) == a:
            c0, clast = b, a
        else:
            return None  # two dead-ends but not adjacent -> malformed, anomaly
        anchor = deadends[c0][0]
        tail = deadends[clast][0]
        ev = f"unfinished: anchor={anchor.id}@cycle0={c0.id}, tail={tail.id}@cyclelast={clast.id}"
    else:
        return None  # 0 or >2 dead-ends -> cannot orient

    # rotate ring so c0 is first
    i = ring.index(c0)
    ordered = ring[i:] + ring[:i]
    return ordered, anchor, tail, ev


def _walk_number(g: PerspectiveGraph, lsb: Node) -> NumberRead | None:
    """Walk a spine from its LSB. spine_i -OP-> bit_i (self-loop => 1);
    spine_i -S-> spine_{i+1}. Stop when no structural successor."""
    spine = []
    bits = []
    cur = lsb
    guard = 0
    while cur is not None and guard < 256:
        guard += 1
        spine.append(cur)
        bitnodes = _op_out(g, cur)
        if len(bitnodes) != 1:
            return None  # not a clean spine vertex
        bit = bitnodes[0]
        bits.append(1 if _has_s_self(g, bit) else 0)
        nxts = [t for t in _s_out(g, cur) if t != bit]
        # next spine vertex: a structural successor that itself has an OP-out (is a spine vertex)
        nxt = None
        for t in nxts:
            if len(_op_out(g, t)) >= 1:
                nxt = t; break
        cur = nxt
    value = sum(b << i for i, b in enumerate(bits))
    return NumberRead(lsb=lsb, bits=bits, value=value, spine=spine,
                      evidence=f"lsb={lsb.id} bits(LSB->MSB)={bits} value={value}")


def decode(g: PerspectiveGraph) -> DecodeResult:
    res = DecodeResult()
    consumed: set[Node] = set()

    # --- Pass 1: operators (structural cycles) ---
    raw_cycles = _find_structural_cycles(g)
    # dedup by node set, keep size in valid operator range
    used_sets = []
    for cyc in raw_cycles:
        fs = frozenset(cyc)
        if fs in used_sets: continue
        if len(cyc) not in _OPERATOR_BY_SIZE: continue
        used_sets.append(fs)
        oriented = _orient_cycle(g, cyc)
        if oriented is None:
            res.anomalies.append(f"cycle size {len(cyc)} nodes {sorted(n.id for n in cyc)}: cannot orient (anchor/tail ambiguous)")
            continue
        ordered, anchor, tail, ev = oriented
        op = _OPERATOR_BY_SIZE[len(ordered)]
        handle = ordered[-1]
        # ports: cycle[0]/cycle[1] OP-out target (operand entry). may be absent mid-rewrite.
        def port_target(node):
            ts = _op_out(g, node)
            ts = [t for t in ts if t not in ordered]  # not an internal op artifact
            if len(ts) == 0: return None
            if len(ts) > 1:
                res.anomalies.append(f"port {node.id} has {len(ts)} OP-out edges (operand-order/port defect)")
            return ts[0]
        port0 = port_target(ordered[0])
        port1 = port_target(ordered[1]) if len(ordered) > 1 else None
        res.operators.append(OperatorRead(cycle=ordered, op=op, handle=handle,
                                           anchor=anchor, tail=tail,
                                           port0=port0, port1=port1, evidence=ev))
        consumed |= set(ordered) | {anchor}
        if tail is not None: consumed.add(tail)

    # --- Pass 2/3: numbers from operator ports, then any remaining spine heads ---
    entries = []
    for o in res.operators:
        for p in (o.port0, o.port1):
            if p is not None and p not in consumed:
                entries.append(p)
    # also any spine head not reachable from a port (free-standing number)
    for n in g.nodes:
        if n in consumed: continue
        if len(_op_out(g, n)) == 1 and not (Edge(n, n, EdgeType.OPERATIONAL) in g):
            # candidate spine vertex; only treat as head if no spine predecessor
            spine_pred = [s for s in _s_in(g, n) if len(_op_out(g, s)) == 1]
            if not spine_pred:
                entries.append(n)

    seen_entry = set()
    for e in entries:
        if e in seen_entry or e in consumed: continue
        seen_entry.add(e)
        nr = _walk_number(g, e)
        if nr is None:
            continue
        res.numbers.append(nr)
        consumed |= set(nr.spine)
        for s in nr.spine:
            for b in _op_out(g, s):
                consumed.add(b)  # bit node

    # --- Pass 4: parameters (bidirectional structural pair, no bit tree) ---
    # A port may attach to EITHER member of the pair, so track both members for
    # render lookup while res.parameters keeps one canonical node per parameter.
    param_members: set[Node] = set()
    for n in g.nodes:
        if n in consumed: continue
        for t in _s_out(g, n):
            if n in _s_out(g, t) and t not in consumed:  # bidirectional
                # neither carries an OP-out spine read => parameter pair
                if not _op_out(g, n) and not _op_out(g, t):
                    res.parameters.append(n)
                    param_members.add(n); param_members.add(t)
                    consumed.add(n); consumed.add(t)
                    break

    # --- Pass 5: remainder = loose nodes ---
    res.loose_nodes = set(g.nodes) - consumed

    # --- assemble expression recursively ---
    # A port may head a number (lsb), a parameter, or a NESTED operator (the
    # port points at that operator's handle = cycle[last]). Resolve by following
    # the handle link, so 3+4=7 prints as "(3 + 4) = 7", not "node12 = 7".
    num_by_lsb = {nr.lsb: nr for nr in res.numbers}
    op_by_handle = {o.handle: o for o in res.operators}
    # also map any cycle member -> its operator, since a port may land on a
    # non-handle cycle node after rewrites; handle is the intended attach point.
    op_by_member = {}
    for o in res.operators:
        for m in o.cycle:
            op_by_member[m] = o

    def render(port, depth=0):
        if port is None:
            return '?'
        if depth > 32:
            return '…'
        if port in num_by_lsb:
            return str(num_by_lsb[port].value)
        if port in param_members:
            return 'x'
        o = op_by_handle.get(port) or op_by_member.get(port)
        if o is not None:
            inner = f"{render(o.port0, depth+1)} {o.op} {render(o.port1, depth+1)}"
            return inner if o.op == '=' else f"({inner})"
        return f'node{port.id}'

    if res.operators:
        # root operator(s): handle not referenced by any other operator's port
        referenced = set()
        for o in res.operators:
            for p in (o.port0, o.port1):
                tgt = op_by_handle.get(p) or op_by_member.get(p)
                if tgt is not None:
                    referenced.add(tgt.handle)
        roots = [o for o in res.operators if o.handle not in referenced]
        if not roots:
            roots = res.operators[:1]
        res.expr = ' ; '.join(
            (f"{render(o.port0)} {o.op} {render(o.port1)}" if o.op == '='
             else f"{render(o.port0)} {o.op} {render(o.port1)}")
            for o in roots
        )
    elif len(res.numbers) == 1:
        res.value = res.numbers[0].value
        res.expr = str(res.value)

    return res
