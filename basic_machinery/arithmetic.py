from __future__ import annotations
from basic_machinery.graph import PerspectiveGraph, Node, EdgeType
from basic_machinery.operations import OperationDefinition, register


# ---------------------------------------------------------------------------
# Pattern building helpers
# ---------------------------------------------------------------------------

def _add_op_node(p: PerspectiveGraph) -> Node:
    """Add an unfinished + operator node (3-cycle + anchor + tail) to pattern graph."""
    from basic_machinery.encoding import build_operator
    return build_operator(p, '+', finished=False)

def _add_finished_op_node(p: PerspectiveGraph) -> Node:
    """Add a finished + operator node (3-cycle + anchor, no tail) to pattern graph."""
    from basic_machinery.encoding import build_operator
    return build_operator(p, '+', finished=True)

def _add_bit_zero(p: PerspectiveGraph) -> Node:
    """Add an empty (zero) bit node to pattern graph."""
    return p.add_node()

def _add_bit_one(p: PerspectiveGraph) -> Node:
    """Add a self-loop (one) bit node to pattern graph."""
    node = p.add_node()
    p.add_edge(node, node, EdgeType.STRUCTURAL)
    return node

def _add_parent(p: PerspectiveGraph, child: Node) -> Node:
    parent = p.add_node()
    p.add_edge(parent, child, EdgeType.STRUCTURAL)
    return parent

def _add_carry(p: PerspectiveGraph, result_node: Node) -> tuple[Node, Node]:
    """
    Carry marker: result_node -OPER-> cycle_a -STRUCT-> cycle_b -STRUCT-> cycle_a.
    """
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


# ---------------------------------------------------------------------------
# add_init rules (4 rules)
# ---------------------------------------------------------------------------
# Pattern: unfinished op + left LSB + right LSB. No result node yet.
# graph2s: transition op to finished, create result node structurally attached.
#          OPERATIONAL scaffold: op->left, op->right, op->result
#          STRUCTURAL output: finished op tag + op->result + result bit tag
# graph2o: wire operational edges op->left, op->right, op->result, carry if needed.
#          STRUCTURAL scaffold: op->left, op->right, op->result
# ---------------------------------------------------------------------------

def _make_add_init_rule(left_bit: int, right_bit: int) -> OperationDefinition:
    result_bit = (left_bit + right_bit) % 2
    carry_out = (left_bit + right_bit) >= 2
    name = f'add_init_{left_bit}{right_bit}'

    # --- Pattern ---
    p = PerspectiveGraph()
    op_node = _add_op_node(p)
    left_pos = _add_bit_one(p) if left_bit else _add_bit_zero(p)
    right_pos = _add_bit_one(p) if right_bit else _add_bit_zero(p)
    p.add_edge(op_node, left_pos, EdgeType.OPERATIONAL)
    p.add_edge(op_node, right_pos, EdgeType.OPERATIONAL)

    # --- graph2s ---
    # OPERATIONAL edges: scaffold mapping (op->left, op->right, op->result)
    # STRUCTURAL edges: finished op tag + op->result + result bit
    # Tail absent from transition -> removed by step 4b
    # Bit nodes absent from transition -> removed by step 4b
    g2s = PerspectiveGraph()
    g2s_op = _add_finished_op_node(g2s)
    g2s_left = g2s.add_node()
    g2s_right = g2s.add_node()
    g2s_result = g2s.add_node()
    # OPERATIONAL scaffold
    g2s.add_edge(g2s_op, g2s_left, EdgeType.OPERATIONAL)
    g2s.add_edge(g2s_op, g2s_right, EdgeType.OPERATIONAL)
    g2s.add_edge(g2s_op, g2s_result, EdgeType.OPERATIONAL)
    # STRUCTURAL output
    g2s.add_edge(g2s_op, g2s_result, EdgeType.STRUCTURAL)
    if result_bit == 1:
        g2s.add_edge(g2s_result, g2s_result, EdgeType.STRUCTURAL)
    if carry_out:
        g2s_carry_a = g2s.add_node()
        g2s_carry_b = g2s.add_node()
        g2s.add_edge(g2s_op, g2s_carry_a, EdgeType.OPERATIONAL)
        g2s.add_edge(g2s_result, g2s_carry_a, EdgeType.STRUCTURAL)
        g2s.add_edge(g2s_carry_a, g2s_carry_b, EdgeType.STRUCTURAL)
        g2s.add_edge(g2s_carry_b, g2s_carry_a, EdgeType.STRUCTURAL)

    # --- graph2o ---
    # STRUCTURAL scaffold: mirrors post-graph2s structure for mapping
    # OPERATIONAL output: op->left, op->right, op->result, carry if needed
    g2o = PerspectiveGraph()
    g2o_op = g2o.add_node()
    g2o_left = g2o.add_node()
    g2o_right = g2o.add_node()
    g2o_result = g2o.add_node()
    # STRUCTURAL scaffold
    g2o.add_edge(g2o_op, g2o_left, EdgeType.STRUCTURAL)
    g2o.add_edge(g2o_op, g2o_right, EdgeType.STRUCTURAL)
    g2o.add_edge(g2o_op, g2o_result, EdgeType.STRUCTURAL)
    # OPERATIONAL output
    g2o.add_edge(g2o_op, g2o_left, EdgeType.OPERATIONAL)
    g2o.add_edge(g2o_op, g2o_right, EdgeType.OPERATIONAL)
    g2o.add_edge(g2o_op, g2o_result, EdgeType.OPERATIONAL)
    if carry_out:
        g2o_carry_a = g2o.add_node()
        g2o_carry_b = g2o.add_node()
        g2o.add_edge(g2o_op, g2o_carry_a, EdgeType.STRUCTURAL)
        g2o.add_edge(g2o_result, g2o_carry_a, EdgeType.OPERATIONAL)
        g2o.add_edge(g2o_carry_a, g2o_carry_b, EdgeType.STRUCTURAL)
        g2o.add_edge(g2o_carry_b, g2o_carry_a, EdgeType.STRUCTURAL)

    return OperationDefinition(name=name, pattern=p, graph2s=g2s, graph2o=g2o)


# ---------------------------------------------------------------------------
# bit_add rules (8 rules)
# ---------------------------------------------------------------------------
# Pattern: finished op + left bit + right bit + parents + result node (+ carry if carry_in)
# graph2s: retag result node. Carry nodes absent -> removed by step 4b.
#          OPERATIONAL scaffold: op->left, op->right, op->result
#          STRUCTURAL output: result bit tag
# graph2o: advance positions to parents, rewire result, add carry if needed.
#          STRUCTURAL scaffold: op->left_parent, op->right_parent, op->result
# ---------------------------------------------------------------------------

def _make_bit_add_rule(left_bit: int, right_bit: int, carry_in: int) -> OperationDefinition:
    total = left_bit + right_bit + carry_in
    result_bit = total % 2
    carry_out = total >= 2
    name = f'bit_add_{left_bit}{right_bit}_c{carry_in}'

    # --- Pattern ---
    p = PerspectiveGraph()
    op_node = _add_finished_op_node(p)
    left_pos = _add_bit_one(p) if left_bit else _add_bit_zero(p)
    right_pos = _add_bit_one(p) if right_bit else _add_bit_zero(p)
    left_parent = _add_parent(p, left_pos)
    right_parent = _add_parent(p, right_pos)
    p.add_edge(op_node, left_pos, EdgeType.OPERATIONAL)
    p.add_edge(op_node, right_pos, EdgeType.OPERATIONAL)
    result_node = _add_result_node(p, op_node)
    if carry_in:
        _add_carry(p, result_node)

    # --- graph2s ---
    # OPERATIONAL scaffold mirrors pattern: op->left, op->right, op->result
    # STRUCTURAL output: new result bit tag
    # carry nodes absent -> removed by step 4b
    # left_pos, right_pos absent -> removed by step 4b
    g2s = PerspectiveGraph()
    g2s_op = g2s.add_node()
    g2s_left_parent = g2s.add_node()
    g2s_right_parent = g2s.add_node()
    g2s_result = g2s.add_node()
    # OPERATIONAL scaffold
    g2s.add_edge(g2s_op, g2s_left_parent, EdgeType.OPERATIONAL)
    g2s.add_edge(g2s_op, g2s_right_parent, EdgeType.OPERATIONAL)
    g2s.add_edge(g2s_op, g2s_result, EdgeType.OPERATIONAL)
    # STRUCTURAL output: result bit tag
    if result_bit == 1:
        g2s.add_edge(g2s_result, g2s_result, EdgeType.STRUCTURAL)

    # --- graph2o ---
    # STRUCTURAL scaffold: op->left_parent, op->right_parent, op->result
    # OPERATIONAL output: advance positions, rewire result, carry if needed
    g2o = PerspectiveGraph()
    g2o_op = g2o.add_node()
    g2o_left_parent = g2o.add_node()
    g2o_right_parent = g2o.add_node()
    g2o_result = g2o.add_node()
    # STRUCTURAL scaffold
    g2o.add_edge(g2o_op, g2o_left_parent, EdgeType.STRUCTURAL)
    g2o.add_edge(g2o_op, g2o_right_parent, EdgeType.STRUCTURAL)
    g2o.add_edge(g2o_op, g2o_result, EdgeType.STRUCTURAL)
    # OPERATIONAL output
    g2o.add_edge(g2o_op, g2o_left_parent, EdgeType.OPERATIONAL)
    g2o.add_edge(g2o_op, g2o_right_parent, EdgeType.OPERATIONAL)
    g2o.add_edge(g2o_op, g2o_result, EdgeType.OPERATIONAL)
    if carry_out:
        g2o_carry_a = g2o.add_node()
        g2o_carry_b = g2o.add_node()
        g2o.add_edge(g2o_op, g2o_carry_a, EdgeType.STRUCTURAL)
        g2o.add_edge(g2o_result, g2o_carry_a, EdgeType.OPERATIONAL)
        g2o.add_edge(g2o_carry_a, g2o_carry_b, EdgeType.STRUCTURAL)
        g2o.add_edge(g2o_carry_b, g2o_carry_a, EdgeType.STRUCTURAL)

    return OperationDefinition(name=name, pattern=p, graph2s=g2s, graph2o=g2o)


# ---------------------------------------------------------------------------
# drain rules (8 rules)
# ---------------------------------------------------------------------------
# Fires when one operand is exhausted (no parent). Active side still has parent.
# graph2s: retag result. Carry absent from transition -> removed.
#          OPERATIONAL scaffold: op->active_pos, op->exhausted, op->result
# graph2o: advance active side to parent, keep exhausted, rewire result.
#          STRUCTURAL scaffold: op->active_parent, op->exhausted, op->result
# ---------------------------------------------------------------------------

def _make_drain_rule(active_side: str, active_bit: int, carry_in: int) -> OperationDefinition:
    total = active_bit + carry_in
    result_bit = total % 2
    carry_out = total >= 2
    name = f'drain_{active_side}_{active_bit}_c{carry_in}'

    # --- Pattern ---
    p = PerspectiveGraph()
    op_node = _add_finished_op_node(p)
    active_pos = _add_bit_one(p) if active_bit else _add_bit_zero(p)
    active_parent = _add_parent(p, active_pos)
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
    # OPERATIONAL scaffold mirrors pattern ops
    # STRUCTURAL output: new result bit tag
    g2s = PerspectiveGraph()
    g2s_op = g2s.add_node()
    g2s_active_parent = g2s.add_node()
    g2s_exhausted = g2s.add_node()
    g2s_result = g2s.add_node()
    if active_side == 'left':
        g2s.add_edge(g2s_op, g2s_active_parent, EdgeType.OPERATIONAL)
        g2s.add_edge(g2s_op, g2s_exhausted, EdgeType.OPERATIONAL)
    else:
        g2s.add_edge(g2s_op, g2s_exhausted, EdgeType.OPERATIONAL)
        g2s.add_edge(g2s_op, g2s_active_parent, EdgeType.OPERATIONAL)
    g2s.add_edge(g2s_op, g2s_result, EdgeType.OPERATIONAL)
    if result_bit == 1:
        g2s.add_edge(g2s_result, g2s_result, EdgeType.STRUCTURAL)

    # --- graph2o ---
    # STRUCTURAL scaffold
    # OPERATIONAL output: advance active to parent, keep exhausted, wire result
    g2o = PerspectiveGraph()
    g2o_op = g2o.add_node()
    g2o_active_parent = g2o.add_node()
    g2o_exhausted = g2o.add_node()
    g2o_result = g2o.add_node()
    if active_side == 'left':
        g2o.add_edge(g2o_op, g2o_active_parent, EdgeType.STRUCTURAL)
        g2o.add_edge(g2o_op, g2o_exhausted, EdgeType.STRUCTURAL)
    else:
        g2o.add_edge(g2o_op, g2o_exhausted, EdgeType.STRUCTURAL)
        g2o.add_edge(g2o_op, g2o_active_parent, EdgeType.STRUCTURAL)
    g2o.add_edge(g2o_op, g2o_result, EdgeType.STRUCTURAL)
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
        g2o.add_edge(g2o_op, g2o_carry_a, EdgeType.STRUCTURAL)
        g2o.add_edge(g2o_result, g2o_carry_a, EdgeType.OPERATIONAL)
        g2o.add_edge(g2o_carry_a, g2o_carry_b, EdgeType.STRUCTURAL)
        g2o.add_edge(g2o_carry_b, g2o_carry_a, EdgeType.STRUCTURAL)

    return OperationDefinition(name=name, pattern=p, graph2s=g2s, graph2o=g2o)


# ---------------------------------------------------------------------------
# add_finalise rules (8 rules)
# ---------------------------------------------------------------------------
# Fires when both positions at MSB (no parents). Op node recycled as result root.
# graph2s: strip op tag (cycle nodes absent -> removed), attach result tree to bare op.
#          OPERATIONAL scaffold: op->left, op->right, op->result
#          STRUCTURAL output: op->result (+ carry overflow if needed)
# graph2o: empty — no new operational edges needed.
#          Parent's op edge to op node preserved via step 6.
# ---------------------------------------------------------------------------

def _make_add_finalise_rule(left_msb: int, right_msb: int, carry_in: int) -> OperationDefinition:
    total = left_msb + right_msb + carry_in
    result_bit = total % 2
    carry_out = total >= 2
    name = f'add_finalise_{left_msb}{right_msb}_c{carry_in}'

    # --- Pattern ---
    p = PerspectiveGraph()
    op_node = _add_finished_op_node(p)
    left_pos = _add_bit_one(p) if left_msb else _add_bit_zero(p)
    right_pos = _add_bit_one(p) if right_msb else _add_bit_zero(p)
    p.add_edge(op_node, left_pos, EdgeType.OPERATIONAL)
    p.add_edge(op_node, right_pos, EdgeType.OPERATIONAL)
    result_node = _add_result_node(p, op_node)
    if carry_in:
        _add_carry(p, result_node)

    # --- graph2s ---
    # OPERATIONAL scaffold: op->left, op->right, op->result
    # STRUCTURAL output: bare op -> result tree
    # Cycle tag nodes absent -> removed by step 4b
    # Bit nodes (left, right) absent -> removed by step 4b
    g2s = PerspectiveGraph()
    g2s_op = g2s.add_node()
    g2s_left = g2s.add_node()
    g2s_right = g2s.add_node()
    g2s_result = g2s.add_node()
    # OPERATIONAL scaffold
    g2s.add_edge(g2s_op, g2s_left, EdgeType.OPERATIONAL)
    g2s.add_edge(g2s_op, g2s_right, EdgeType.OPERATIONAL)
    g2s.add_edge(g2s_op, g2s_result, EdgeType.OPERATIONAL)
    # STRUCTURAL output
    if result_bit == 1:
        g2s.add_edge(g2s_result, g2s_result, EdgeType.STRUCTURAL)
    if carry_out:
        g2s_msb = g2s.add_node()
        g2s.add_edge(g2s_msb, g2s_msb, EdgeType.STRUCTURAL)
        g2s.add_edge(g2s_op, g2s_msb, EdgeType.STRUCTURAL)
        g2s.add_edge(g2s_msb, g2s_result, EdgeType.STRUCTURAL)
    else:
        g2s.add_edge(g2s_op, g2s_result, EdgeType.STRUCTURAL)

    # --- graph2o ---
    # Empty — no operational edges to write.
    # Step 6 reattaches any stripped structural edges where endpoints survive.
    g2o = PerspectiveGraph()

    return OperationDefinition(name=name, pattern=p, graph2s=g2s, graph2o=g2o)


# ---------------------------------------------------------------------------
# tombstone_gc rule
# ---------------------------------------------------------------------------
# Tombstone marker: operational self-loop on node.
# Pattern: tombstoned -OPER_SELF-> tombstoned, tombstoned -STRUCT-> child
# graph2s: child survives with tombstone operational self-loop.
#          OPERATIONAL scaffold: tombstoned self-loop (input node detection)
#          OPERATIONAL output on child (written via step 5 as output_type=STRUCTURAL... 
#          wait — Pass 1 strips OPERATIONAL, outputs STRUCTURAL)
# NOTE: tombstone_gc is unusual — the marker IS operational and needs to survive.
# Solution: encode child survival via OPERATIONAL scaffold edge tombstoned->child,
# then graph2o writes the tombstone self-loop onto child.
# ---------------------------------------------------------------------------

def _make_tombstone_gc_rule() -> OperationDefinition:
    # --- Pattern ---
    p = PerspectiveGraph()
    tombstoned = p.add_node()
    p.add_edge(tombstoned, tombstoned, EdgeType.OPERATIONAL)
    child = p.add_node()
    p.add_edge(tombstoned, child, EdgeType.STRUCTURAL)

    # --- graph2s ---
    # OPERATIONAL scaffold: tombstoned->child (makes child reachable via follow_mapping)
    # tombstoned has self-loop as input anchor, child reachable from it
    # STRUCTURAL output: none (child survives bare structurally)
    # tombstoned absent from structural output -> removed by step 4b
    g2s = PerspectiveGraph()
    g2s_tombstoned = g2s.add_node()
    g2s_child = g2s.add_node()
    g2s.add_edge(g2s_tombstoned, g2s_tombstoned, EdgeType.OPERATIONAL)
    g2s.add_edge(g2s_tombstoned, g2s_child, EdgeType.OPERATIONAL)

    # --- graph2o ---
    # STRUCTURAL scaffold: child (bare node, input anchor)
    # OPERATIONAL output: child gets tombstone self-loop
    g2o = PerspectiveGraph()
    g2o_child = g2o.add_node()
    g2o.add_edge(g2o_child, g2o_child, EdgeType.OPERATIONAL)

    return OperationDefinition(name='tombstone_gc', pattern=p, graph2s=g2s, graph2o=g2o)


# ---------------------------------------------------------------------------
# Register all rules
# ---------------------------------------------------------------------------

for _l in range(2):
    for _r in range(2):
        register(_make_add_init_rule(_l, _r))

for _l in range(2):
    for _r in range(2):
        for _c in range(2):
            register(_make_bit_add_rule(_l, _r, _c))

for _b in range(2):
    for _c in range(2):
        register(_make_drain_rule('left', _b, _c))

for _b in range(2):
    for _c in range(2):
        register(_make_drain_rule('right', _b, _c))

for _l in range(2):
    for _r in range(2):
        for _c in range(2):
            register(_make_add_finalise_rule(_l, _r, _c))

register(_make_tombstone_gc_rule())
