from __future__ import annotations
from basic_machinery.graph import PerspectiveGraph, Node, EdgeType
from basic_machinery.operations import OperationDefinition, register
from basic_machinery.encoding import OpTag


# ---------------------------------------------------------------------------
# Pattern building helpers
# ---------------------------------------------------------------------------

def _add_op_node(p: PerspectiveGraph) -> tuple[Node, OpTag]:
    from basic_machinery.encoding import build_operator
    return build_operator(p, '+', finished=False)

def _add_finished_op_node(p: PerspectiveGraph) -> tuple[Node, OpTag]:
    from basic_machinery.encoding import build_operator
    return build_operator(p, '+', finished=True)

def _add_bit_zero(p: PerspectiveGraph) -> Node:
    return p.add_node()

def _add_bit_one(p: PerspectiveGraph) -> Node:
    node = p.add_node()
    p.add_edge(node, node, EdgeType.STRUCTURAL)
    return node

def _add_parent(p: PerspectiveGraph, child: Node) -> Node:
    parent = p.add_node()
    p.add_edge(parent, child, EdgeType.STRUCTURAL)
    return parent

def _add_carry(p: PerspectiveGraph, result_node: Node) -> tuple[Node, Node]:
    cycle_a = p.add_node()
    cycle_b = p.add_node()
    p.add_edge(result_node, cycle_a, EdgeType.OPERATIONAL)
    p.add_edge(cycle_a, cycle_b, EdgeType.STRUCTURAL)
    p.add_edge(cycle_b, cycle_a, EdgeType.STRUCTURAL)
    return cycle_a, cycle_b

def _add_result_node(p: PerspectiveGraph, op_node: Node) -> Node:
    result = p.add_node()
    p.add_edge(op_node, result, EdgeType.OPERATIONAL)
    return result


def _make_input_graph(
    pattern: PerspectiveGraph,
    boundary_nodes: set[Node] | None = None,
) -> tuple[PerspectiveGraph, dict[Node, Node]]:
    """
    Clone pattern and encode OPERATIONAL edges as marker chains.
    STRUCTURAL edges copied unchanged.
    OPERATIONAL self-loops converted to STRUCTURAL self-loops.
    OPERATIONAL A->B becomes A->[S]->m->[S]->B, m->[OP]->m.
    Boundary nodes get a structural edge to a shared placeholder.
    """
    g = PerspectiveGraph()
    node_map: dict[Node, Node] = {}
    for node in pattern.nodes:
        node_map[node] = g.add_node()
    for edge in pattern.edges:
        src = node_map[edge.source]
        tgt = node_map[edge.target]
        if edge.edge_type == EdgeType.STRUCTURAL:
            g.add_edge(src, tgt, EdgeType.STRUCTURAL)
        elif edge.source == edge.target:
            g.add_edge(src, tgt, EdgeType.STRUCTURAL)
        else:
            m = g.add_node()
            g.add_edge(src, m, EdgeType.STRUCTURAL)
            g.add_edge(m, tgt, EdgeType.STRUCTURAL)
            g.add_edge(m, m, EdgeType.OPERATIONAL)
    if boundary_nodes:
        placeholder = g.add_node()
        g.add_edge(placeholder, placeholder, EdgeType.STRUCTURAL)
        g.add_edge(placeholder, placeholder, EdgeType.OPERATIONAL)
        for bn in boundary_nodes:
            g.add_edge(node_map[bn], placeholder, EdgeType.STRUCTURAL)
    return g, node_map


def _add_op_marker_chain(g: PerspectiveGraph, src: Node, tgt: Node) -> None:
    """Add a marker chain encoding an OPERATIONAL edge src->tgt in the output side."""
    m = g.add_node()
    g.add_edge(src, m, EdgeType.STRUCTURAL)
    g.add_edge(m, tgt, EdgeType.STRUCTURAL)
    g.add_edge(m, m, EdgeType.OPERATIONAL)


def _add_output_carry(
    g: PerspectiveGraph,
    result_node: Node,
    map_source: Node,
) -> tuple[Node, Node]:
    """
    Atomically build an output carry 2-cycle AND its incoming OPERATIONAL
    mapping edges, so the carry nodes classify as output (output_only) rather
    than input under step-2 (output_only = has_incoming - has_outgoing).

    Builds, as a single unit:
      - carry_a, carry_b nodes
      - structural 2-cycle  carry_a <-> carry_b
      - result_node -> carry_a  (output OPERATIONAL edge, encoded as a marker chain)
      - map_source -> carry_a, map_source -> carry_b  (incoming MAPPING edges)

    The mapping edges are the fix: without them step-2 puts carry_a/carry_b in
    input_nodes, inflating the step-3 input subgraph and tripping the exact-match
    size guard for every carry rule.

    map_source is the conservative correspondent (per the conservative_mapping
    decision): the input node on the result line (in_result, or in_tail for
    add_init). A born carry-out has no input-carry correspondent, so the
    result-line input is the most defensible source. Identity/id preservation is
    an incremental-recompute optimisation, not a correctness property — the
    output graph is a fresh layer delta — so the exact real node each carry node
    receives does not matter, only that they classify and construct as output.
    """
    carry_a = g.add_node()
    carry_b = g.add_node()
    g.add_edge(carry_a, carry_b, EdgeType.STRUCTURAL)
    g.add_edge(carry_b, carry_a, EdgeType.STRUCTURAL)
    g.add_edge(result_node, carry_a, EdgeType.STRUCTURAL)
    _add_op_marker_chain(g, result_node, carry_a)
    # The mapping edges — the actual fix.
    g.add_edge(map_source, carry_a, EdgeType.OPERATIONAL)
    g.add_edge(map_source, carry_b, EdgeType.OPERATIONAL)
    return carry_a, carry_b


def _add_finished_tag_output(g: PerspectiveGraph, op: Node, tag: OpTag) -> None:
    size = len(tag.cycle_nodes)
    for i in range(size):
        g.add_edge(tag.cycle_nodes[i], tag.cycle_nodes[(i + 1) % size], EdgeType.STRUCTURAL)
    g.add_edge(op, tag.cycle_nodes[0], EdgeType.STRUCTURAL)
    g.add_edge(tag.cycle_nodes[0], tag.anchor, EdgeType.STRUCTURAL)


def _add_unfinished_tag_output(g: PerspectiveGraph, op: Node, tag: OpTag) -> None:
    size = len(tag.cycle_nodes)
    for i in range(size - 1):
        g.add_edge(tag.cycle_nodes[i], tag.cycle_nodes[i + 1], EdgeType.STRUCTURAL)
    g.add_edge(tag.cycle_nodes[-1], tag.cycle_nodes[0], EdgeType.STRUCTURAL)
    g.add_edge(tag.cycle_nodes[-1], tag.tail, EdgeType.STRUCTURAL)
    g.add_edge(op, tag.cycle_nodes[0], EdgeType.STRUCTURAL)
    g.add_edge(tag.cycle_nodes[0], tag.anchor, EdgeType.STRUCTURAL)


# ---------------------------------------------------------------------------
# add_init rules — successor-free, port-threading (rebuilt 2026-06-10)
#
# Window = {operator 3-cycle, left LSB, right LSB}. No successor node is modelled;
# multi-bit-ness is expressed by the LSB's (STRUCTURAL,out) crossing to the shared
# placeholder (the onward chain hop). LSB-terminal axis = whether that crossing is
# present: multi -> present, single -> absent.
#
# Mapping (verified by trace on 3+4, 3+5, 1+2):
#   in_cyc[i] -> out_cyc[i]   (handle == cyc[last], mapped exactly ONCE)
#   in_anchor -> out_anchor
#   in_tail   -> out_result, out_buffer        (tail repurposed as buffer)
#   in_left   -> out_cyc[0] / in_right -> out_cyc[1]   (PORT threads the successor
#               pathway forward; omitted for a single-bit side with no successor)
#
# Result construction (add_init_result_construction): result hangs off the BUFFER,
# never the operator. result MSB -S-> buffer ; result LSB -OP-> buffer (marker
# chain) ; handle -S-> buffer (tail attachment survives). MSB==LSB at init so both
# originate from the one result node. Carry: born 2-cycle off result, mapping
# edges sourced from in_tail.
# ---------------------------------------------------------------------------

def _typed_input_graph(p: PerspectiveGraph, specs: dict):
    """Clone p into an input-side graph; attach boundary nodes in `specs` to one
    shared placeholder using the typed crossing encoding
    (operational_crossing_needs_marker_chain):
        (S,out): B->ph ; (S,in): ph->B ;
        (O,out): chain B->m->ph ; (O,in): chain ph->m->B.
    Pattern OPERATIONAL A->B become marker chains; op self-loops -> struct self-loops.
    Returns (g, node_map, placeholder)."""
    g = PerspectiveGraph()
    nm: dict[Node, Node] = {}
    for node in p.nodes:
        nm[node] = g.add_node()
    for e in p.edges:
        s, t = nm[e.source], nm[e.target]
        if e.edge_type == EdgeType.STRUCTURAL:
            g.add_edge(s, t, EdgeType.STRUCTURAL)
        elif e.source == e.target:
            g.add_edge(s, t, EdgeType.STRUCTURAL)
        else:
            _add_op_marker_chain(g, s, t)
    ph = None
    if specs:
        ph = g.add_node()
        g.add_edge(ph, ph, EdgeType.STRUCTURAL)
        g.add_edge(ph, ph, EdgeType.OPERATIONAL)
        for bn, (etype, direction) in specs.items():
            B = nm[bn]
            if etype == EdgeType.STRUCTURAL and direction == 'out':
                g.add_edge(B, ph, EdgeType.STRUCTURAL)
            elif etype == EdgeType.STRUCTURAL and direction == 'in':
                g.add_edge(ph, B, EdgeType.STRUCTURAL)
            elif etype == EdgeType.OPERATIONAL and direction == 'out':
                _add_op_marker_chain(g, B, ph)
            elif etype == EdgeType.OPERATIONAL and direction == 'in':
                _add_op_marker_chain(g, ph, B)
            else:
                raise ValueError(f"bad spec for {bn}: {(etype, direction)}")
    return g, nm, ph


def _make_add_init_rule(left_bit: int, right_bit: int,
                        left_single: bool = False, right_single: bool = False) -> OperationDefinition:
    result_bit = (left_bit + right_bit) % 2
    carry_out  = (left_bit + right_bit) >= 2
    ls = 's' if left_single else 'm'
    rs = 's' if right_single else 'm'
    name = f'add_init_{left_bit}{right_bit}_{ls}{rs}'

    from basic_machinery.encoding import build_operator
    p = PerspectiveGraph()
    handle, tag = build_operator(p, '+', finished=False)
    cyc = tag.cycle_nodes

    def _bit(v):
        n = p.add_node()
        if v == 1:
            p.add_edge(n, n, EdgeType.STRUCTURAL)
        return n
    ll = _bit(left_bit); rl = _bit(right_bit)
    p.add_edge(cyc[0], ll, EdgeType.OPERATIONAL)
    p.add_edge(cyc[1], rl, EdgeType.OPERATIONAL)

    specs = {handle: (EdgeType.OPERATIONAL, 'in')}
    if not left_single:  specs[ll] = (EdgeType.STRUCTURAL, 'out')
    if not right_single: specs[rl] = (EdgeType.STRUCTURAL, 'out')
    g2, nm, ph = _typed_input_graph(p, specs)

    in_handle = nm[handle]
    in_cyc    = [nm[c] for c in cyc]
    in_anchor = nm[tag.anchor]
    in_tail   = nm[tag.tail]
    in_left   = nm[ll]; in_right = nm[rl]

    sz = len(cyc)
    out_cyc = [g2.add_node() for _ in range(sz - 1)]
    out_handle = g2.add_node(); out_cyc.append(out_handle)   # out_cyc[last] == handle
    out_anchor = g2.add_node()
    out_result = g2.add_node()
    out_buffer = g2.add_node()

    # mapping
    for ic, oc in zip(in_cyc, out_cyc):
        g2.add_edge(ic, oc, EdgeType.OPERATIONAL)
    g2.add_edge(in_anchor, out_anchor, EdgeType.OPERATIONAL)
    g2.add_edge(in_tail,   out_result, EdgeType.OPERATIONAL)
    g2.add_edge(in_tail,   out_buffer, EdgeType.OPERATIONAL)
    if not left_single:  g2.add_edge(in_left,  out_cyc[0], EdgeType.OPERATIONAL)
    if not right_single: g2.add_edge(in_right, out_cyc[1], EdgeType.OPERATIONAL)

    # operator 3-ring + anchor off cyc0 + tail attachment handle->buffer
    for i in range(sz):
        g2.add_edge(out_cyc[i], out_cyc[(i + 1) % sz], EdgeType.STRUCTURAL)
    g2.add_edge(out_cyc[0], out_anchor, EdgeType.STRUCTURAL)
    g2.add_edge(out_handle, out_buffer, EdgeType.STRUCTURAL)

    # result off buffer
    if result_bit == 1:
        g2.add_edge(out_result, out_result, EdgeType.STRUCTURAL)
    g2.add_edge(out_result, out_buffer, EdgeType.STRUCTURAL)
    _add_op_marker_chain(g2, out_result, out_buffer)

    if carry_out:
        ca = g2.add_node(); cb = g2.add_node()
        g2.add_edge(ca, cb, EdgeType.STRUCTURAL)
        g2.add_edge(cb, ca, EdgeType.STRUCTURAL)
        g2.add_edge(out_result, ca, EdgeType.STRUCTURAL)
        _add_op_marker_chain(g2, out_result, ca)
        g2.add_edge(in_tail, ca, EdgeType.OPERATIONAL)
        g2.add_edge(in_tail, cb, EdgeType.OPERATIONAL)

    return OperationDefinition(name=name, pattern=p, graph2=g2)

# ---------------------------------------------------------------------------
# bit_add rules (8 rules)
# ---------------------------------------------------------------------------

def _make_bit_add_rule(left_bit: int, right_bit: int, carry_in: int) -> OperationDefinition:
    total      = left_bit + right_bit + carry_in
    result_bit = total % 2
    carry_out  = total >= 2
    name = f'bit_add_{left_bit}{right_bit}_c{carry_in}'

    # --- Pattern ---
    p = PerspectiveGraph()
    op_node, op_tag = _add_finished_op_node(p)
    left_pos     = _add_bit_one(p) if left_bit  else _add_bit_zero(p)
    right_pos    = _add_bit_one(p) if right_bit else _add_bit_zero(p)
    left_parent  = _add_parent(p, left_pos)
    right_parent = _add_parent(p, right_pos)
    p.add_edge(op_node, left_pos,  EdgeType.OPERATIONAL)
    p.add_edge(op_node, right_pos, EdgeType.OPERATIONAL)
    result_node = _add_result_node(p, op_node)
    # Structural edges written by add_init/bit_add output side
    p.add_edge(op_node, left_pos,   EdgeType.STRUCTURAL)
    p.add_edge(op_node, right_pos,  EdgeType.STRUCTURAL)
    p.add_edge(op_node, result_node, EdgeType.STRUCTURAL)
    if carry_in:
        carry_a, carry_b = _add_carry(p, result_node)

    # --- graph2 ---
    g2, p2g = _make_input_graph(p, boundary_nodes={op_node, left_parent, right_parent})
    in_op           = p2g[op_node]
    in_cycles       = [p2g[c] for c in op_tag.cycle_nodes]
    in_anchor       = p2g[op_tag.anchor]
    in_left_parent  = p2g[left_parent]
    in_right_parent = p2g[right_parent]
    in_result       = p2g[result_node]

    out_op           = g2.add_node()
    out_cycles       = [g2.add_node() for _ in op_tag.cycle_nodes]
    out_anchor       = g2.add_node()
    out_left_parent  = g2.add_node()
    out_right_parent = g2.add_node()
    out_result       = g2.add_node()

    g2.add_edge(in_op,           out_op,           EdgeType.OPERATIONAL)
    for ic, oc in zip(in_cycles, out_cycles):
        g2.add_edge(ic, oc, EdgeType.OPERATIONAL)
    g2.add_edge(in_anchor,       out_anchor,       EdgeType.OPERATIONAL)
    g2.add_edge(in_left_parent,  out_left_parent,  EdgeType.OPERATIONAL)
    g2.add_edge(in_right_parent, out_right_parent, EdgeType.OPERATIONAL)
    g2.add_edge(in_result,       out_result,       EdgeType.OPERATIONAL)
    if carry_in:
        in_carry_a  = p2g[carry_a]
        in_carry_b  = p2g[carry_b]
        out_carry_a = g2.add_node()
        out_carry_b = g2.add_node()
        g2.add_edge(in_carry_a, out_carry_a, EdgeType.OPERATIONAL)
        g2.add_edge(in_carry_b, out_carry_b, EdgeType.OPERATIONAL)

    out_tag = OpTag(cycle_nodes=out_cycles, anchor=out_anchor, tail=None)
    _add_finished_tag_output(g2, out_op, out_tag)
    g2.add_edge(out_op, out_left_parent,  EdgeType.STRUCTURAL)
    g2.add_edge(out_op, out_right_parent, EdgeType.STRUCTURAL)
    g2.add_edge(out_op, out_result,       EdgeType.STRUCTURAL)
    if result_bit == 1:
        g2.add_edge(out_result, out_result, EdgeType.STRUCTURAL)
    # Born carry-out (no input carry correspondent): source mapping edges from
    # in_result, the result-line correspondent. Builds the 2-cycle, the output
    # marker chain, and the incoming mapping edges atomically.
    if carry_out:
        _add_output_carry(g2, out_result, in_result)

    # OPERATIONAL output as marker chains
    _add_op_marker_chain(g2, out_op, out_left_parent)
    _add_op_marker_chain(g2, out_op, out_right_parent)
    _add_op_marker_chain(g2, out_op, out_result)

    return OperationDefinition(name=name, pattern=p, graph2=g2)


# ---------------------------------------------------------------------------
# drain rules (16 rules: 2 sides x 2 active bits x 2 exhausted bits x 2 carry)
#
# Fires when one operand is exhausted (no structural parent above it) and
# the other still has bits remaining (has a structural parent above it).
# The exhausted operand and active_pos are consumed; op advances its pointer
# to active_parent (the next bit level of the active operand).
# ---------------------------------------------------------------------------

def _make_drain_rule(active_side: str, active_bit: int, exhausted_bit: int, carry_in: int) -> OperationDefinition:
    total      = active_bit + carry_in
    result_bit = total % 2
    carry_out  = total >= 2
    name = f'drain_{active_side}_{active_bit}e{exhausted_bit}_c{carry_in}'

    # --- Pattern ---
    # active_parent has a structural parent outside the match (boundary).
    # exhausted_pos has NO structural parent — it is the MSB of its operand.
    # active_pos is the current bit of the active operand (has active_parent above).
    p = PerspectiveGraph()
    op_node, op_tag = _add_finished_op_node(p)
    active_pos    = _add_bit_one(p) if active_bit    else _add_bit_zero(p)
    active_parent = _add_parent(p, active_pos)
    exhausted_pos = _add_bit_one(p) if exhausted_bit else _add_bit_zero(p)
    if active_side == 'left':
        p.add_edge(op_node, active_pos,    EdgeType.OPERATIONAL)
        p.add_edge(op_node, exhausted_pos, EdgeType.OPERATIONAL)
    else:
        p.add_edge(op_node, exhausted_pos, EdgeType.OPERATIONAL)
        p.add_edge(op_node, active_pos,    EdgeType.OPERATIONAL)
    result_node = _add_result_node(p, op_node)
    # Structural edges written by previous rule output
    p.add_edge(op_node, active_pos,    EdgeType.STRUCTURAL)
    p.add_edge(op_node, exhausted_pos, EdgeType.STRUCTURAL)
    p.add_edge(op_node, result_node,   EdgeType.STRUCTURAL)
    if carry_in:
        carry_a, carry_b = _add_carry(p, result_node)

    # --- graph2 ---
    # active_parent is boundary (has external structural connections to sibling subtree).
    # exhausted_pos is NOT boundary — it has no parent, so no external connections.
    # active_pos is consumed (no output mapping -> deleted).
    # exhausted_pos is consumed (no output mapping -> deleted).
    # op advances: operational edge repoints from active_pos to active_parent.
    g2, p2g = _make_input_graph(p, boundary_nodes={op_node, active_parent})
    in_op            = p2g[op_node]
    in_cycles        = [p2g[c] for c in op_tag.cycle_nodes]
    in_anchor        = p2g[op_tag.anchor]
    in_active_parent = p2g[active_parent]
    in_result        = p2g[result_node]
    # in_active_pos and in_exhausted have no output mapping -> deleted

    out_op            = g2.add_node()
    out_cycles        = [g2.add_node() for _ in op_tag.cycle_nodes]
    out_anchor        = g2.add_node()
    out_active_parent = g2.add_node()
    out_result        = g2.add_node()

    g2.add_edge(in_op,            out_op,            EdgeType.OPERATIONAL)
    for ic, oc in zip(in_cycles, out_cycles):
        g2.add_edge(ic, oc, EdgeType.OPERATIONAL)
    g2.add_edge(in_anchor,        out_anchor,        EdgeType.OPERATIONAL)
    g2.add_edge(in_active_parent, out_active_parent, EdgeType.OPERATIONAL)
    g2.add_edge(in_result,        out_result,        EdgeType.OPERATIONAL)
    if carry_in:
        in_carry_a  = p2g[carry_a]
        in_carry_b  = p2g[carry_b]
        out_carry_a = g2.add_node()
        out_carry_b = g2.add_node()
        g2.add_edge(in_carry_a, out_carry_a, EdgeType.OPERATIONAL)
        g2.add_edge(in_carry_b, out_carry_b, EdgeType.OPERATIONAL)

    # STRUCTURAL output: finished op tag + op->active_parent + op->result
    out_tag = OpTag(cycle_nodes=out_cycles, anchor=out_anchor, tail=None)
    _add_finished_tag_output(g2, out_op, out_tag)
    g2.add_edge(out_op, out_active_parent, EdgeType.STRUCTURAL)
    g2.add_edge(out_op, out_result,        EdgeType.STRUCTURAL)
    if result_bit == 1:
        g2.add_edge(out_result, out_result, EdgeType.STRUCTURAL)
    # Born carry-out: source mapping edges from in_result (result-line correspondent).
    if carry_out:
        _add_output_carry(g2, out_result, in_result)

    # OPERATIONAL output: op->active_parent (advances pointer), op->result
    _add_op_marker_chain(g2, out_op, out_active_parent)
    _add_op_marker_chain(g2, out_op, out_result)

    return OperationDefinition(name=name, pattern=p, graph2=g2)


# ---------------------------------------------------------------------------
# add_finalise rules (8 rules)
# ---------------------------------------------------------------------------

def _make_add_finalise_rule(left_msb: int, right_msb: int, carry_in: int) -> OperationDefinition:
    total      = left_msb + right_msb + carry_in
    result_bit = total % 2
    carry_out  = total >= 2
    name = f'add_finalise_{left_msb}{right_msb}_c{carry_in}'

    # --- Pattern ---
    p = PerspectiveGraph()
    op_node, op_tag = _add_finished_op_node(p)
    left_pos  = _add_bit_one(p) if left_msb  else _add_bit_zero(p)
    right_pos = _add_bit_one(p) if right_msb else _add_bit_zero(p)
    p.add_edge(op_node, left_pos,  EdgeType.OPERATIONAL)
    p.add_edge(op_node, right_pos, EdgeType.OPERATIONAL)
    result_node = _add_result_node(p, op_node)
    # Structural edges written by bit_add/drain output side
    p.add_edge(op_node, left_pos,   EdgeType.STRUCTURAL)
    p.add_edge(op_node, right_pos,  EdgeType.STRUCTURAL)
    p.add_edge(op_node, result_node, EdgeType.STRUCTURAL)
    if carry_in:
        carry_a, carry_b = _add_carry(p, result_node)

    # --- graph2 ---
    g2, p2g = _make_input_graph(p, boundary_nodes={op_node})
    in_op     = p2g[op_node]
    in_result = p2g[result_node]

    out_op     = g2.add_node()
    out_result = g2.add_node()

    g2.add_edge(in_op,     out_op,     EdgeType.OPERATIONAL)
    g2.add_edge(in_result, out_result, EdgeType.OPERATIONAL)

    if result_bit == 1:
        g2.add_edge(out_result, out_result, EdgeType.STRUCTURAL)
    if carry_out:
        out_msb = g2.add_node()
        g2.add_edge(out_msb, out_msb, EdgeType.STRUCTURAL)
        g2.add_edge(out_op,  out_msb,    EdgeType.STRUCTURAL)
        g2.add_edge(out_msb, out_result, EdgeType.STRUCTURAL)
        # Incoming MAPPING edge: without it, out_msb (born overflow bit) has no
        # incoming operational edge and step-2 misclassifies it as an input node.
        # Sourced from in_result (the result-line correspondent). This is a
        # mapping instruction, not an output operational edge, so it does not
        # violate finalise's "no operational output" design.
        g2.add_edge(in_result, out_msb, EdgeType.OPERATIONAL)
    else:
        g2.add_edge(out_op, out_result, EdgeType.STRUCTURAL)

    # No operational output edges needed for finalise — op node recycled as result root,
    # parent's existing operational edge stays attached to it.

    return OperationDefinition(name=name, pattern=p, graph2=g2)


# ---------------------------------------------------------------------------
# tombstone_gc rule
# ---------------------------------------------------------------------------

def _make_tombstone_gc_rule() -> OperationDefinition:
    # --- Pattern ---
    p = PerspectiveGraph()
    tombstoned = p.add_node()
    p.add_edge(tombstoned, tombstoned, EdgeType.OPERATIONAL)
    child = p.add_node()
    p.add_edge(tombstoned, child, EdgeType.STRUCTURAL)

    # --- graph2 ---
    # tombstoned: operational self-loop -> structural self-loop in input side.
    # tombstoned is boundary (has parent outside match).
    # child is boundary (will be reconnected after tombstone removal).
    g2 = PerspectiveGraph()
    g2_tombstoned = g2.add_node()
    g2_child      = g2.add_node()
    g2.add_edge(g2_tombstoned, g2_tombstoned, EdgeType.OPERATIONAL)  # input: self-loop signal
    g2.add_edge(g2_tombstoned, g2_child,      EdgeType.OPERATIONAL)  # tombstoned -> child: no output = delete tombstoned

    return OperationDefinition(name='tombstone_gc', pattern=p, graph2=g2)


# ---------------------------------------------------------------------------
# Register all rules
# ---------------------------------------------------------------------------

for _l in range(2):
    for _r in range(2):
        for _ls in [False, True]:
            for _rs in [False, True]:
                register(_make_add_init_rule(_l, _r, _ls, _rs))

for _l in range(2):
    for _r in range(2):
        for _c in range(2):
            register(_make_bit_add_rule(_l, _r, _c))

for _b in range(2):
    for _e in range(2):
        for _c in range(2):
            register(_make_drain_rule('left', _b, _e, _c))

for _b in range(2):
    for _e in range(2):
        for _c in range(2):
            register(_make_drain_rule('right', _b, _e, _c))

for _l in range(2):
    for _r in range(2):
        for _c in range(2):
            register(_make_add_finalise_rule(_l, _r, _c))

register(_make_tombstone_gc_rule())
