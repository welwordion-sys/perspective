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
# add_init rules (4 rules)
# ---------------------------------------------------------------------------
# add_init rules (8 rules)
#
# Fires on an unfinished op pointing to LSBs of both operands.
# left_single / right_single: True if that operand is a single-bit number
#   (no structural parent above its LSB node).
#
# All variants:
#   - Convert op tag from unfinished to finished
#   - Compute LSB result bit (and carry if sum >= 2)
#   - Create result node (from tail) + buffer node (MSB placeholder)
#   - result_lsb ->S-> buffer  (structural chain will grow toward buffer)
#   - result_lsb ->OP-> buffer (fixed anchor: LSB always knows where MSB is)
#   - op ->OP-> result_lsb     (op holds result LSB pointer)
#
# For multi-bit operands: op advances pointer to parent (parent is boundary).
# For single-bit operands: operand pointer consumed (deleted), no parent to advance to.
# ---------------------------------------------------------------------------

def _make_add_init_rule(left_bit: int, right_bit: int,
                        left_single: bool = False, right_single: bool = False) -> OperationDefinition:
    result_bit = (left_bit + right_bit) % 2
    carry_out  = (left_bit + right_bit) >= 2
    ls = 's' if left_single  else 'm'  # s=single, m=multi
    rs = 's' if right_single else 'm'
    name = f'add_init_{left_bit}{right_bit}_{ls}{rs}'

    # --- Pattern ---
    p = PerspectiveGraph()
    op_node, op_tag = _add_op_node(p)
    left_pos  = _add_bit_one(p) if left_bit  else _add_bit_zero(p)
    right_pos = _add_bit_one(p) if right_bit else _add_bit_zero(p)
    p.add_edge(op_node, left_pos,  EdgeType.OPERATIONAL)
    p.add_edge(op_node, right_pos, EdgeType.OPERATIONAL)
    # For multi-bit operands, add a parent node (marks that a parent exists above)
    if not left_single:
        left_parent = _add_parent(p, left_pos)
    if not right_single:
        right_parent = _add_parent(p, right_pos)

    # --- Boundary nodes ---
    # op is always boundary (has parent equality node above).
    # multi-bit parents are boundary (have sibling subtrees outside match).
    boundary = {op_node}
    if not left_single:
        boundary.add(left_parent)
    if not right_single:
        boundary.add(right_parent)

    # --- graph2 (unified transition) ---
    g2, p2g = _make_input_graph(p, boundary_nodes=boundary)
    in_op     = p2g[op_node]
    in_cycles = [p2g[c] for c in op_tag.cycle_nodes]
    in_anchor = p2g[op_tag.anchor]
    in_tail   = p2g[op_tag.tail]
    in_left   = p2g[left_pos]
    in_right  = p2g[right_pos]
    if not left_single:
        in_left_parent  = p2g[left_parent]
    if not right_single:
        in_right_parent = p2g[right_parent]

    # Output nodes
    out_op     = g2.add_node()
    out_cycles = [g2.add_node() for _ in op_tag.cycle_nodes]
    out_anchor = g2.add_node()
    out_result = g2.add_node()   # result LSB (from tail)
    out_buffer = g2.add_node()   # MSB placeholder buffer
    if not left_single:
        out_left_parent  = g2.add_node()
    else:
        out_left_zero = g2.add_node()   # implicit zero above single-bit left operand
    if not right_single:
        out_right_parent = g2.add_node()
    else:
        out_right_zero = g2.add_node()  # implicit zero above single-bit right operand

    # OPERATIONAL input->output mapping
    g2.add_edge(in_op,     out_op,     EdgeType.OPERATIONAL)
    for ic, oc in zip(in_cycles, out_cycles):
        g2.add_edge(ic, oc, EdgeType.OPERATIONAL)
    g2.add_edge(in_anchor, out_anchor, EdgeType.OPERATIONAL)
    # in_tail -> out_result (reuse), out_buffer (new)
    g2.add_edge(in_tail,   out_result, EdgeType.OPERATIONAL)
    g2.add_edge(in_tail,   out_buffer, EdgeType.OPERATIONAL)
    # Multi-bit: parent survives (left_pos deleted, consumed)
    # Single-bit: bit node maps to a fresh zero (implicit zero above MSB)
    if not left_single:
        g2.add_edge(in_left_parent, out_left_parent, EdgeType.OPERATIONAL)
    else:
        g2.add_edge(in_left,        out_left_zero,   EdgeType.OPERATIONAL)
    if not right_single:
        g2.add_edge(in_right_parent, out_right_parent, EdgeType.OPERATIONAL)
    else:
        g2.add_edge(in_right,        out_right_zero,   EdgeType.OPERATIONAL)

    # STRUCTURAL output: finished op tag topology
    out_tag = OpTag(cycle_nodes=out_cycles, anchor=out_anchor, tail=None)
    _add_finished_tag_output(g2, out_op, out_tag)
    # Op structural edges to current operand positions and result
    out_left_pos  = out_left_parent  if not left_single  else out_left_zero
    out_right_pos = out_right_parent if not right_single else out_right_zero
    g2.add_edge(out_op, out_left_pos,  EdgeType.STRUCTURAL)
    g2.add_edge(out_op, out_right_pos, EdgeType.STRUCTURAL)
    g2.add_edge(out_op, out_result,    EdgeType.STRUCTURAL)
    # Result bit value
    if result_bit == 1:
        g2.add_edge(out_result, out_result, EdgeType.STRUCTURAL)
    # Result LSB -> buffer (structural chain start + operational anchor)
    g2.add_edge(out_result, out_buffer, EdgeType.STRUCTURAL)
    _add_op_marker_chain(g2, out_result, out_buffer)

    # OPERATIONAL output: op->left_pos, op->right_pos, op->result
    _add_op_marker_chain(g2, out_op, out_left_pos)
    _add_op_marker_chain(g2, out_op, out_right_pos)
    _add_op_marker_chain(g2, out_op, out_result)

    # Mark boundary output nodes with placeholder connection so step 4c
    # preserves their external edges.
    # op and multi-bit parent nodes have external connections.
    # The placeholder node in the transition (already exists from input side).
    placeholder_nodes = [n for n in g2.nodes
                         if (EdgeType.STRUCTURAL in [e.edge_type for e in g2.edges_from(n)] or True)
                         and any(e.source==n and e.target==n and e.edge_type==EdgeType.STRUCTURAL for e in g2.edges)
                         and any(e.source==n and e.target==n and e.edge_type==EdgeType.OPERATIONAL for e in g2.edges)]
    if placeholder_nodes:
        ph = placeholder_nodes[0]
        g2.add_edge(out_op, ph, EdgeType.STRUCTURAL)
        if not left_single:
            g2.add_edge(out_left_pos, ph, EdgeType.STRUCTURAL)
        if not right_single:
            g2.add_edge(out_right_pos, ph, EdgeType.STRUCTURAL)

    if carry_out:
        # Born carry-out: no input carry correspondent. Source the mapping edges
        # from in_tail (the result-line input), the most defensible correspondent.
        _add_output_carry(g2, out_result, in_tail)

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
