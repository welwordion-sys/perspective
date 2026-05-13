from __future__ import annotations
from basic_machinery.graph import PerspectiveGraph, Node, EdgeType
from basic_machinery.operations import OperationDefinition, register


# ---------------------------------------------------------------------------
# Pattern building helpers
# ---------------------------------------------------------------------------

def _add_op_node(p: PerspectiveGraph) -> Node:
    """Add an unfinished + operator node (3-cycle + anchor) to pattern graph."""
    from basic_machinery.encoding import build_operator
    return build_operator(p, '+', finished=False)


def _add_bit_zero(p: PerspectiveGraph) -> Node:
    """Add an empty (zero) bit node to pattern graph."""
    return p.add_node()  # empty — no structural edges


def _add_bit_one(p: PerspectiveGraph) -> Node:
    """Add a self-loop (one) bit node to pattern graph."""
    node = p.add_node()
    p.add_edge(node, node, EdgeType.STRUCTURAL)
    return node


def _add_parent(p: PerspectiveGraph, child: Node) -> Node:
    """
    Add a parent node connected to child via structural edge.
    Encodes the position advance target — parent is where the
    position cursor moves after this bit step.
    """
    parent = p.add_node()
    p.add_edge(parent, child, EdgeType.STRUCTURAL)
    return parent


def _add_carry(p: PerspectiveGraph, result_node: Node) -> tuple[Node, Node]:
    """
    Add a carry marker 2-cycle to pattern graph, attached to result_node
    via an operational edge from result_node to one cycle node.
    Returns (cycle_a, cycle_b) where result_node -OPER-> cycle_a -STRUCT-> cycle_b -STRUCT-> cycle_a.
    """
    cycle_a = p.add_node()
    cycle_b = p.add_node()
    p.add_edge(result_node, cycle_a, EdgeType.OPERATIONAL)
    p.add_edge(cycle_a, cycle_b, EdgeType.STRUCTURAL)
    p.add_edge(cycle_b, cycle_a, EdgeType.STRUCTURAL)
    return cycle_a, cycle_b


def _add_result_node(p: PerspectiveGraph, op_node: Node) -> Node:
    """
    Add a result accumulator node connected to op_node via operational edge.
    The result node is the current leaf of the growing result tree.
    """
    result = p.add_node()
    p.add_edge(op_node, result, EdgeType.OPERATIONAL)
    return result


# ---------------------------------------------------------------------------
# add_init rules (4 rules — first bit step, no result node yet)
# ---------------------------------------------------------------------------
# Pattern: op node + left LSB + right LSB. No parents, no result node.
# add_init only initialises the result accumulator.
# Position advance is handled by bit_add/drain rules which carry parent context.
# graph2s: create result node with correct bit tag
# graph2o: wire op -> left_lsb, op -> right_lsb, op -> result
# ---------------------------------------------------------------------------

def _make_add_init_rule(left_bit: int, right_bit: int) -> OperationDefinition:
    result_bit = (left_bit + right_bit) % 2
    carry_out = (left_bit + right_bit) >= 2
    name = f'add_init_{left_bit}{right_bit}'

    # --- Pattern ---
    # Unfinished op node (has tail), two LSB bit nodes, no result node yet.
    p = PerspectiveGraph()
    op_node = _add_op_node(p)  # builds unfinished = cycle + anchor + tail
    left_pos = _add_bit_one(p) if left_bit else _add_bit_zero(p)
    right_pos = _add_bit_one(p) if right_bit else _add_bit_zero(p)
    p.add_edge(op_node, left_pos, EdgeType.OPERATIONAL)
    p.add_edge(op_node, right_pos, EdgeType.OPERATIONAL)

    # --- graph2s ---
    # Transition shows op_node as finished (cycle + anchor, no tail).
    # Tail is absent from transition — removed by step 4b.
    # Result node created fresh, attached structurally to op_node.
    # Op_node survives because 3-cycle gives it outgoing structural edges.
    # Bit nodes absent from transition — removed by step 4b.
    g2s = PerspectiveGraph()
    from basic_machinery.encoding import build_operator as _build_op
    g2s_op = _build_op(g2s, '+', finished=True)   # cycle + anchor, no tail
    g2s_result = g2s.add_node()
    if result_bit == 1:
        g2s.add_edge(g2s_result, g2s_result, EdgeType.STRUCTURAL)
    g2s.add_edge(g2s_op, g2s_result, EdgeType.STRUCTURAL)

    if carry_out:
        g2s_carry_a = g2s.add_node()
        g2s_carry_b = g2s.add_node()
        g2s.add_edge(g2s_result, g2s_carry_a, EdgeType.STRUCTURAL)
        g2s.add_edge(g2s_carry_a, g2s_carry_b, EdgeType.STRUCTURAL)
        g2s.add_edge(g2s_carry_b, g2s_carry_a, EdgeType.STRUCTURAL)

    # --- graph2o ---
    # Wire op -> left_lsb, op -> right_lsb, op -> result.
    # Carry wired to result if carry_out.
    g2o = PerspectiveGraph()
    g2o_op = g2o.add_node()
    g2o_left = g2o.add_node()
    g2o_right = g2o.add_node()
    g2o_result = g2o.add_node()
    g2o.add_edge(g2o_op, g2o_left, EdgeType.OPERATIONAL)
    g2o.add_edge(g2o_op, g2o_right, EdgeType.OPERATIONAL)
    g2o.add_edge(g2o_op, g2o_result, EdgeType.OPERATIONAL)

    if carry_out:
        g2o_carry_a = g2o.add_node()
        g2o_carry_b = g2o.add_node()
        g2o.add_edge(g2o_result, g2o_carry_a, EdgeType.OPERATIONAL)
        g2o.add_edge(g2o_carry_a, g2o_carry_b, EdgeType.STRUCTURAL)
        g2o.add_edge(g2o_carry_b, g2o_carry_a, EdgeType.STRUCTURAL)

    return OperationDefinition(name=name, pattern=p, graph2s=g2s, graph2o=g2o)


# ---------------------------------------------------------------------------
# bit_add rules (8 rules — mid-reduction, result node exists)
# ---------------------------------------------------------------------------
# Pattern: op node + left bit + right bit + parents + result node
# Carry present/absent encoded in result node's outgoing operational edges.
# graph2s: retag result node for new result bit, remove carry if consumed
# graph2o: advance position edges, rewire op -> result, add carry if produced
# ---------------------------------------------------------------------------

def _make_bit_add_rule(
    left_bit: int,
    right_bit: int,
    carry_in: int,
) -> OperationDefinition:
    total = left_bit + right_bit + carry_in
    result_bit = total % 2
    carry_out = total >= 2
    name = f'bit_add_{left_bit}{right_bit}_c{carry_in}'

    # --- Pattern ---
    p = PerspectiveGraph()
    op_node = _add_op_node(p)
    left_pos = _add_bit_one(p) if left_bit else _add_bit_zero(p)
    right_pos = _add_bit_one(p) if right_bit else _add_bit_zero(p)
    left_parent = _add_parent(p, left_pos)
    right_parent = _add_parent(p, right_pos)
    p.add_edge(op_node, left_pos, EdgeType.OPERATIONAL)
    p.add_edge(op_node, right_pos, EdgeType.OPERATIONAL)

    # Result node — connected to op via operational edge
    result_node = _add_result_node(p, op_node)

    # Carry — attached to result node if carry_in
    if carry_in:
        _add_carry(p, result_node)

    # --- graph2s ---
    # New result node with correct bit tag.
    # carry_in node pair absent from transition — removed by step 4b.
    g2s = PerspectiveGraph()
    g2s_result = g2s.add_node()
    if result_bit == 1:
        g2s.add_edge(g2s_result, g2s_result, EdgeType.STRUCTURAL)

    # --- graph2o ---
    # Advance position edges to parents, rewire result, add carry if needed.
    g2o = PerspectiveGraph()
    g2o_op = g2o.add_node()
    g2o_left_parent = g2o.add_node()
    g2o_right_parent = g2o.add_node()
    g2o_result = g2o.add_node()
    g2o.add_edge(g2o_op, g2o_left_parent, EdgeType.OPERATIONAL)
    g2o.add_edge(g2o_op, g2o_right_parent, EdgeType.OPERATIONAL)
    g2o.add_edge(g2o_op, g2o_result, EdgeType.OPERATIONAL)

    if carry_out:
        g2o_carry_a = g2o.add_node()
        g2o_carry_b = g2o.add_node()
        g2o.add_edge(g2o_result, g2o_carry_a, EdgeType.OPERATIONAL)
        g2o.add_edge(g2o_carry_a, g2o_carry_b, EdgeType.STRUCTURAL)
        g2o.add_edge(g2o_carry_b, g2o_carry_a, EdgeType.STRUCTURAL)

    return OperationDefinition(name=name, pattern=p, graph2s=g2s, graph2o=g2o)


# ---------------------------------------------------------------------------
# drain rules (8 rules — one position exhausted, other still has bits)
# ---------------------------------------------------------------------------
# Fires when one operand has reached its MSB (no parent in pattern).
# The exhausted side's bit is propagated with carry if present.
# Position edge on exhausted side is not advanced further.
# ---------------------------------------------------------------------------

def _make_drain_rule(
    active_side: str,  # 'left' or 'right' — the side still being drained
    active_bit: int,
    carry_in: int,
) -> OperationDefinition:
    total = active_bit + carry_in
    result_bit = total % 2
    carry_out = total >= 2
    name = f'drain_{active_side}_{active_bit}_c{carry_in}'

    # --- Pattern ---
    p = PerspectiveGraph()
    op_node = _add_op_node(p)

    # Active side has a parent — position still advancing
    active_pos = _add_bit_one(p) if active_bit else _add_bit_zero(p)
    active_parent = _add_parent(p, active_pos)

    # Exhausted side has no parent — bare bit node at MSB
    # We use 0 for exhausted side (MSB of shorter number is 0 padding)
    exhausted_pos = _add_bit_zero(p)

    if active_side == 'left':
        p.add_edge(op_node, active_pos, EdgeType.OPERATIONAL)
        p.add_edge(op_node, exhausted_pos, EdgeType.OPERATIONAL)
    else:
        p.add_edge(op_node, exhausted_pos, EdgeType.OPERATIONAL)
        p.add_edge(op_node, active_pos, EdgeType.OPERATIONAL)

    result_node = _add_result_node(p, op_node)

    if carry_in:
        _add_carry(p, result_node)

    # --- graph2s ---
    g2s = PerspectiveGraph()
    g2s_result = g2s.add_node()
    if result_bit == 1:
        g2s.add_edge(g2s_result, g2s_result, EdgeType.STRUCTURAL)

    # --- graph2o ---
    # Active side advances to parent.
    # Exhausted side stays at same node (no parent to advance to).
    g2o = PerspectiveGraph()
    g2o_op = g2o.add_node()
    g2o_active_parent = g2o.add_node()
    g2o_exhausted = g2o.add_node()
    g2o_result = g2o.add_node()

    if active_side == 'left':
        g2o.add_edge(g2o_op, g2o_active_parent, EdgeType.OPERATIONAL)
        g2o.add_edge(g2o_op, g2o_exhausted, EdgeType.OPERATIONAL)
    else:
        g2o.add_edge(g2o_op, g2o_exhausted, EdgeType.OPERATIONAL)
        g2o.add_edge(g2o_op, g2o_active_parent, EdgeType.OPERATIONAL)

    g2o.add_edge(g2o_op, g2o_result, EdgeType.OPERATIONAL)

    if carry_out:
        g2o_carry_a = g2o.add_node()
        g2o_carry_b = g2o.add_node()
        g2o.add_edge(g2o_result, g2o_carry_a, EdgeType.OPERATIONAL)
        g2o.add_edge(g2o_carry_a, g2o_carry_b, EdgeType.STRUCTURAL)
        g2o.add_edge(g2o_carry_b, g2o_carry_a, EdgeType.STRUCTURAL)

    return OperationDefinition(name=name, pattern=p, graph2s=g2s, graph2o=g2o)


# ---------------------------------------------------------------------------
# add_finalise rules (8 rules — both MSBs exhausted, carry in or not)
# ---------------------------------------------------------------------------
# Fires when both positions are at MSB (no parents in pattern).
# Op node is recycled as the new result root — its tag structure is stripped
# by step 4b (cycle nodes + anchor absent from transition), leaving a bare
# node that inherits the parent's existing operational edge.
# Result tree is structurally connected to the recycled op node.
# MSB values can be 0 or 1 — 4 combinations x 2 carry states = 8 rules.
# ---------------------------------------------------------------------------

def _make_add_finalise_rule(
    left_msb: int,
    right_msb: int,
    carry_in: int,
) -> OperationDefinition:
    total = left_msb + right_msb + carry_in
    result_bit = total % 2
    carry_out = total >= 2  # carry out beyond MSB — needs extra result node above
    name = f'add_finalise_{left_msb}{right_msb}_c{carry_in}'

    # --- Pattern ---
    p = PerspectiveGraph()
    op_node = _add_op_node(p)

    left_pos = _add_bit_one(p) if left_msb else _add_bit_zero(p)
    right_pos = _add_bit_one(p) if right_msb else _add_bit_zero(p)
    p.add_edge(op_node, left_pos, EdgeType.OPERATIONAL)
    p.add_edge(op_node, right_pos, EdgeType.OPERATIONAL)

    result_node = _add_result_node(p, op_node)

    if carry_in:
        _add_carry(p, result_node)

    # --- graph2s ---
    # Op node survives — recycled as result root.
    # Its cycle tag nodes are absent from transition, removed by step 4b.
    # Result node survives with correct bit tag.
    # If carry_out: a new MSB node (value=1) is created above result node,
    # structurally connected. Op node becomes root of this new structure.
    g2s = PerspectiveGraph()
    g2s_op = g2s.add_node()       # recycled op node — bare, no tag
    g2s_result = g2s.add_node()
    if result_bit == 1:
        g2s.add_edge(g2s_result, g2s_result, EdgeType.STRUCTURAL)

    if carry_out:
        g2s_msb = g2s.add_node()
        g2s.add_edge(g2s_msb, g2s_msb, EdgeType.STRUCTURAL)  # value=1
        g2s.add_edge(g2s_op, g2s_msb, EdgeType.STRUCTURAL)
        g2s.add_edge(g2s_msb, g2s_result, EdgeType.STRUCTURAL)
    else:
        g2s.add_edge(g2s_op, g2s_result, EdgeType.STRUCTURAL)

    # --- graph2o ---
    # No new operational edges needed.
    # Parent's operational edge to op node is preserved via step 6
    # since op node survives as g2s_op.
    g2o = PerspectiveGraph()

    return OperationDefinition(name=name, pattern=p, graph2s=g2s, graph2o=g2o)


# ---------------------------------------------------------------------------
# tombstone_gc rule
# ---------------------------------------------------------------------------
# Propagates tombstone marker down detached subtrees for garbage collection.
# A tombstoned node passes its tombstone to its structural children.
# Tombstone marker: operational self-loop on the node.
# ---------------------------------------------------------------------------

def _make_tombstone_gc_rule() -> OperationDefinition:
    # --- Pattern ---
    p = PerspectiveGraph()
    tombstoned = p.add_node()
    p.add_edge(tombstoned, tombstoned, EdgeType.OPERATIONAL)  # tombstone marker
    child = p.add_node()
    p.add_edge(tombstoned, child, EdgeType.STRUCTURAL)

    # --- graph2s ---
    # Child gets tombstone marker. Parent is removed.
    g2s = PerspectiveGraph()
    g2s_child = g2s.add_node()
    g2s.add_edge(g2s_child, g2s_child, EdgeType.OPERATIONAL)

    # --- graph2o ---
    g2o = PerspectiveGraph()

    return OperationDefinition(
        name='tombstone_gc',
        pattern=p,
        graph2s=g2s,
        graph2o=g2o,
    )


# ---------------------------------------------------------------------------
# Register all rules
# ---------------------------------------------------------------------------

# add_init — 4 rules
for _l in range(2):
    for _r in range(2):
        register(_make_add_init_rule(_l, _r))

# bit_add — 8 rules
for _l in range(2):
    for _r in range(2):
        for _c in range(2):
            register(_make_bit_add_rule(_l, _r, _c))

# drain — left active, right exhausted: 4 rules (bit x carry)
for _b in range(2):
    for _c in range(2):
        register(_make_drain_rule('left', _b, _c))

# drain — right active, left exhausted: 4 rules
for _b in range(2):
    for _c in range(2):
        register(_make_drain_rule('right', _b, _c))

# add_finalise — 8 rules (left_msb x right_msb x carry_in)
for _l in range(2):
    for _r in range(2):
        for _c in range(2):
            register(_make_add_finalise_rule(_l, _r, _c))

# tombstone_gc
register(_make_tombstone_gc_rule())
