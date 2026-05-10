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
# Transition graph helpers
# ---------------------------------------------------------------------------

def _make_advance_graph2o(
    left_parent: Node,
    right_parent: Node,
    result_node: Node,
    op_node: Node,
    add_carry: bool,
) -> PerspectiveGraph:
    """
    Build graph2o for a bit rule.
    Strips structural edges, outputs operational edges:
    - op_node -> left_parent  (position advances to parent)
    - op_node -> right_parent
    - op_node -> result_node  (result edge preserved)
    - result_node -> carry_a  (only if add_carry=True)

    All nodes referenced here must already exist in the pattern graph
    so the node_map can resolve them.
    """
    g = PerspectiveGraph()
    # Nodes in graph2o must mirror the pattern nodes that survive.
    # We build a minimal graph referencing only the nodes we need.
    # _apply_pass matches input nodes (those with outgoing strip-type edges
    # in the transition) against the post-strip subgraph, then follows
    # strip-type (structural) edges to build the output node map.
    # Since we want to output operational edges, graph2o's strip_type=STRUCTURAL.
    # Input nodes in graph2o = nodes with outgoing STRUCTURAL edges in graph2o.
    # We add no structural edges here — all nodes are isolated input nodes,
    # each mapping to their counterpart in the node_map from graph2s.
    # Operational edges between them are then written into the target graph.

    g_op = g.add_node()       # maps to op_node
    g_left = g.add_node()     # maps to left_parent
    g_right = g.add_node()    # maps to right_parent
    g_result = g.add_node()   # maps to result_node

    g.add_edge(g_op, g_left, EdgeType.OPERATIONAL)
    g.add_edge(g_op, g_right, EdgeType.OPERATIONAL)
    g.add_edge(g_op, g_result, EdgeType.OPERATIONAL)

    if add_carry:
        g_carry_a = g.add_node()
        g_carry_b = g.add_node()
        g.add_edge(g_result, g_carry_a, EdgeType.OPERATIONAL)
        g.add_edge(g_carry_a, g_carry_b, EdgeType.STRUCTURAL)
        g.add_edge(g_carry_b, g_carry_a, EdgeType.STRUCTURAL)

    return g


# ---------------------------------------------------------------------------
# add_init rules (4 rules — first bit step, no result node yet)
# ---------------------------------------------------------------------------
# Pattern: op node + left LSB + right LSB + left parent + right parent
# No result node yet — distinguishes init from mid-reduction.
# graph2s: create result node with correct bit tag
# graph2o: wire op -> left_parent, op -> right_parent, op -> result
# ---------------------------------------------------------------------------

def _make_add_init_rule(
    left_bit: int,
    right_bit: int,
) -> OperationDefinition:
    result_bit = (left_bit + right_bit) % 2
    carry_out = (left_bit + right_bit) >= 2
    name = f'add_init_{left_bit}{right_bit}'

    # --- Pattern ---
    p = PerspectiveGraph()
    op_node = _add_op_node(p)
    left_pos = _add_bit_one(p) if left_bit else _add_bit_zero(p)
    right_pos = _add_bit_one(p) if right_bit else _add_bit_zero(p)
    left_parent = _add_parent(p, left_pos)
    right_parent = _add_parent(p, right_pos)
    p.add_edge(op_node, left_pos, EdgeType.OPERATIONAL)
    p.add_edge(op_node, right_pos, EdgeType.OPERATIONAL)
    # No result node in pattern — op has exactly 2 operational edges here.

    # --- graph2s ---
    # Strips operational edges, outputs structural.
    # Creates the result node with correct bit tag.
    # result_bit=1: self-loop on result node
    # result_bit=0: empty result node
    g2s = PerspectiveGraph()
    g2s_result = g2s.add_node()
    if result_bit == 1:
        g2s.add_edge(g2s_result, g2s_result, EdgeType.STRUCTURAL)

    # --- graph2o ---
    # Strips structural, outputs operational.
    # Wires op -> left_parent, op -> right_parent, op -> result.
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
    # carry_in node pair is absent from transition — removed by step 4b.
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
# drain rules (2 rules — one position exhausted, other still has bits)
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
# add_finalise rule
# ---------------------------------------------------------------------------
# Fires when both positions are at MSB (no parents in pattern).
# Rewires the parent of the op node to the result root.
# Op node and its tag are removed. Operand trees are tombstoned.
# ---------------------------------------------------------------------------

def _make_add_finalise_rule(carry_in: int) -> OperationDefinition:
    name = f'add_finalise_c{carry_in}'

    # --- Pattern ---
    p = PerspectiveGraph()
    op_node = _add_op_node(p)

    # Both positions at MSB — bare bit nodes, no parents
    left_msb = _add_bit_zero(p)   # MSB of left operand (exhausted)
    right_msb = _add_bit_zero(p)  # MSB of right operand (exhausted)
    p.add_edge(op_node, left_msb, EdgeType.OPERATIONAL)
    p.add_edge(op_node, right_msb, EdgeType.OPERATIONAL)

    result_node = _add_result_node(p, op_node)

    if carry_in:
        _add_carry(p, result_node)

    # --- graph2s ---
    # If carry_in: create a new result node above current result (carry bit = 1)
    # No carry_in: result node is already the final MSB
    g2s = PerspectiveGraph()
    if carry_in:
        # New MSB node with value 1, structurally connected to old result
        g2s_new_msb = g2s.add_node()
        g2s_old_result = g2s.add_node()
        g2s.add_edge(g2s_new_msb, g2s_new_msb, EdgeType.STRUCTURAL)  # tag as 1
        g2s.add_edge(g2s_new_msb, g2s_old_result, EdgeType.STRUCTURAL)

    # --- graph2o ---
    # Op node is removed. External operational edge from parent of op
    # is reattached to result root by step 6.
    # No new operational edges needed — result root is already wired externally.
    g2o = PerspectiveGraph()

    return OperationDefinition(name=name, pattern=p, graph2s=g2s, graph2o=g2o)


# ---------------------------------------------------------------------------
# tombstone_gc rule
# ---------------------------------------------------------------------------
# Propagates tombstone marker down detached subtrees for garbage collection.
# A tombstoned node passes its tombstone to its structural children.
# Tombstone marker: a self-loop operational edge on the node.
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

# drain — left active, right exhausted: 4 rules (bit × carry)
for _b in range(2):
    for _c in range(2):
        register(_make_drain_rule('left', _b, _c))

# drain — right active, left exhausted: 4 rules
for _b in range(2):
    for _c in range(2):
        register(_make_drain_rule('right', _b, _c))

# add_finalise — 2 rules (carry in or not)
for _c in range(2):
    register(_make_add_finalise_rule(_c))

# tombstone_gc
register(_make_tombstone_gc_rule())
