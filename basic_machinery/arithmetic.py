from __future__ import annotations
from basic_machinery.graph import PerspectiveGraph, Node, EdgeType
from basic_machinery.operations import OperationDefinition, register
from basic_machinery.encoding import OpTag


# ---------------------------------------------------------------------------
# Pattern building helpers
# ---------------------------------------------------------------------------

def _add_op_node(p: PerspectiveGraph) -> tuple[Node, OpTag]:
    """Add an unfinished + operator node (3-cycle + anchor + tail) to pattern graph."""
    from basic_machinery.encoding import build_operator
    return build_operator(p, '+', finished=False)

def _add_finished_op_node(p: PerspectiveGraph) -> tuple[Node, OpTag]:
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


def _make_input_graph(pattern: PerspectiveGraph) -> tuple[PerspectiveGraph, dict[Node, Node]]:
    """
    Clone pattern and encode OPERATIONAL edges as marker chains.
    Returns (input_graph, node_map) where node_map maps pattern nodes → input nodes.

    The input graph is the input side of a transition graph — it must mirror
    exactly what the real graph's matched subgraph looks like after step 1's
    marker insertion. Step 1 converts each OPERATIONAL edge A→B into:
        A→[S]→marker→[S]→B  with  marker→[OP]→marker (operational self-loop)

    STRUCTURAL edges are copied unchanged.
    OPERATIONAL self-loops (source == target) are copied as STRUCTURAL self-loops —
    they represent node identity signals (e.g. tombstone pattern), not traversal edges,
    and are matched before step 1 fires so no marker conversion is needed.

    node_map covers only the real pattern nodes — marker nodes inserted here
    are internal to the encoding and not referenced by rule builders.
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
            # Operational self-loop — identity signal, not a traversal edge.
            # Convert to structural self-loop so the pattern topology is preserved
            # for matching (pattern match runs before step 1, so the real graph
            # still has the operational self-loop at match time; this conversion
            # only affects the transition input subgraph used in step 3).
            g.add_edge(src, tgt, EdgeType.STRUCTURAL)
        else:
            # OPERATIONAL edge A→B: encode as marker chain A→[S]→m→[S]→B
            # with m→[OP]→m to signal this was a converted operational edge.
            m = g.add_node()
            g.add_edge(src, m, EdgeType.STRUCTURAL)
            g.add_edge(m, tgt, EdgeType.STRUCTURAL)
            g.add_edge(m, m, EdgeType.OPERATIONAL)
    return g, node_map


def _add_finished_tag_output(
    g: PerspectiveGraph,
    op: Node,
    tag: OpTag,
) -> None:
    """
    Write the STRUCTURAL edges that describe a finished op tag's final state
    onto the output nodes. Mirrors the topology of _tag_cycle exactly.
    """
    size = len(tag.cycle_nodes)
    for i in range(size):
        g.add_edge(tag.cycle_nodes[i], tag.cycle_nodes[(i + 1) % size], EdgeType.STRUCTURAL)
    g.add_edge(op, tag.cycle_nodes[0], EdgeType.STRUCTURAL)
    g.add_edge(tag.cycle_nodes[0], tag.anchor, EdgeType.STRUCTURAL)


def _add_unfinished_tag_output(
    g: PerspectiveGraph,
    op: Node,
    tag: OpTag,
) -> None:
    """
    Write the STRUCTURAL edges that describe an unfinished op tag's final state
    onto the output nodes. Mirrors the topology of _tag_cycle_plus exactly.
    """
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
# Pattern: unfinished op + left LSB + right LSB. No result node yet.
# graph2s input: clone of pattern with OPERATIONAL→STRUCTURAL.
# graph2s output: finished op tag nodes + result node (cloned from tail).
#   Tail input → result output. Left/right inputs have no output → deleted.
# graph2o input: clone of post-graph2s state.
# graph2o output: op→left, op→right, op→result operational edges.
# ---------------------------------------------------------------------------

def _make_add_init_rule(left_bit: int, right_bit: int) -> OperationDefinition:
    result_bit = (left_bit + right_bit) % 2
    carry_out = (left_bit + right_bit) >= 2
    name = f'add_init_{left_bit}{right_bit}'

    # --- Pattern ---
    p = PerspectiveGraph()
    op_node, op_tag = _add_op_node(p)  # unfinished: has tail
    left_pos = _add_bit_one(p) if left_bit else _add_bit_zero(p)
    right_pos = _add_bit_one(p) if right_bit else _add_bit_zero(p)
    p.add_edge(op_node, left_pos, EdgeType.OPERATIONAL)
    p.add_edge(op_node, right_pos, EdgeType.OPERATIONAL)

    # --- graph2s ---
    # Input side: clone of pattern with OPERATIONAL→STRUCTURAL
    g2s, p2g = _make_input_graph(p)
    # Mapped input nodes
    in_op = p2g[op_node]
    in_cycles = [p2g[c] for c in op_tag.cycle_nodes]
    in_anchor = p2g[op_tag.anchor]
    in_tail = p2g[op_tag.tail]
    in_left = p2g[left_pos]
    in_right = p2g[right_pos]

    # Output nodes: finished op tag (no tail) + left + right + result (cloned from tail)
    out_op = g2s.add_node()
    out_cycles = [g2s.add_node() for _ in op_tag.cycle_nodes]
    out_anchor = g2s.add_node()
    out_left = g2s.add_node()
    out_right = g2s.add_node()
    out_result = g2s.add_node()

    # OPERATIONAL input→output pairs
    # op, cycle nodes, anchor, left, right survive; tail→result (clone)
    g2s.add_edge(in_op, out_op, EdgeType.OPERATIONAL)
    for ic, oc in zip(in_cycles, out_cycles):
        g2s.add_edge(ic, oc, EdgeType.OPERATIONAL)
    g2s.add_edge(in_anchor, out_anchor, EdgeType.OPERATIONAL)
    g2s.add_edge(in_left, out_left, EdgeType.OPERATIONAL)
    g2s.add_edge(in_right, out_right, EdgeType.OPERATIONAL)
    g2s.add_edge(in_tail, out_result, EdgeType.OPERATIONAL)

    # STRUCTURAL output: finished op tag topology
    out_tag = OpTag(cycle_nodes=out_cycles, anchor=out_anchor, tail=None)
    _add_finished_tag_output(g2s, out_op, out_tag)
    # op→result + result bit; left and right survive bare (bit value stripped by pass)
    g2s.add_edge(out_op, out_result, EdgeType.STRUCTURAL)
    if result_bit == 1:
        g2s.add_edge(out_result, out_result, EdgeType.STRUCTURAL)
    if left_bit == 1:
        g2s.add_edge(out_left, out_left, EdgeType.STRUCTURAL)
    if right_bit == 1:
        g2s.add_edge(out_right, out_right, EdgeType.STRUCTURAL)
    if carry_out:
        out_carry_a = g2s.add_node()
        out_carry_b = g2s.add_node()
        g2s.add_edge(out_result, out_carry_a, EdgeType.STRUCTURAL)
        g2s.add_edge(out_carry_a, out_carry_b, EdgeType.STRUCTURAL)
        g2s.add_edge(out_carry_b, out_carry_a, EdgeType.STRUCTURAL)

    # --- graph2o ---
    # Post-graph2s state: finished op tag, op→left, op→right, op→result (STRUCTURAL),
    # left and right retain their bit value tags, result has its bit tag.
    post = PerspectiveGraph()
    post_op, post_op_tag = _add_finished_op_node(post)
    post_left = post.add_node()
    post_right = post.add_node()
    post_result = post.add_node()
    post.add_edge(post_op, post_left, EdgeType.STRUCTURAL)
    post.add_edge(post_op, post_right, EdgeType.STRUCTURAL)
    post.add_edge(post_op, post_result, EdgeType.STRUCTURAL)
    if left_bit == 1:
        post.add_edge(post_left, post_left, EdgeType.STRUCTURAL)
    if right_bit == 1:
        post.add_edge(post_right, post_right, EdgeType.STRUCTURAL)
    if result_bit == 1:
        post.add_edge(post_result, post_result, EdgeType.STRUCTURAL)
    if carry_out:
        post_carry_a = post.add_node()
        post_carry_b = post.add_node()
        post.add_edge(post_result, post_carry_a, EdgeType.STRUCTURAL)
        post.add_edge(post_carry_a, post_carry_b, EdgeType.STRUCTURAL)
        post.add_edge(post_carry_b, post_carry_a, EdgeType.STRUCTURAL)

    g2o, post2g = _make_input_graph(post)
    in2_op = post2g[post_op]
    in2_left = post2g[post_left]
    in2_right = post2g[post_right]
    in2_result = post2g[post_result]

    out2_op = g2o.add_node()
    out2_left = g2o.add_node()
    out2_right = g2o.add_node()
    out2_result = g2o.add_node()

    g2o.add_edge(in2_op, out2_op, EdgeType.OPERATIONAL)
    g2o.add_edge(in2_left, out2_left, EdgeType.OPERATIONAL)
    g2o.add_edge(in2_right, out2_right, EdgeType.OPERATIONAL)
    g2o.add_edge(in2_result, out2_result, EdgeType.OPERATIONAL)
    if carry_out:
        in2_carry_a = post2g[post_carry_a]
        in2_carry_b = post2g[post_carry_b]
        out2_carry_a = g2o.add_node()
        out2_carry_b = g2o.add_node()
        g2o.add_edge(in2_carry_a, out2_carry_a, EdgeType.OPERATIONAL)
        g2o.add_edge(in2_carry_b, out2_carry_b, EdgeType.OPERATIONAL)

    # STRUCTURAL output: op tag + op→left + op→right + op→result (preserved)
    out2_op_tag = OpTag(
        cycle_nodes=[g2o.add_node() for _ in post_op_tag.cycle_nodes],
        anchor=g2o.add_node(),
        tail=None,
    )
    _add_finished_tag_output(g2o, out2_op, out2_op_tag)
    g2o.add_edge(out2_op, out2_left, EdgeType.STRUCTURAL)
    g2o.add_edge(out2_op, out2_right, EdgeType.STRUCTURAL)
    g2o.add_edge(out2_op, out2_result, EdgeType.STRUCTURAL)
    if left_bit == 1:
        g2o.add_edge(out2_left, out2_left, EdgeType.STRUCTURAL)
    if right_bit == 1:
        g2o.add_edge(out2_right, out2_right, EdgeType.STRUCTURAL)
    if result_bit == 1:
        g2o.add_edge(out2_result, out2_result, EdgeType.STRUCTURAL)

    # OPERATIONAL output: op→left, op→right, op→result
    g2o.add_edge(out2_op, out2_left, EdgeType.OPERATIONAL)
    g2o.add_edge(out2_op, out2_right, EdgeType.OPERATIONAL)
    g2o.add_edge(out2_op, out2_result, EdgeType.OPERATIONAL)
    if carry_out:
        g2o.add_edge(out2_result, out2_carry_a, EdgeType.OPERATIONAL)
        g2o.add_edge(out2_carry_a, out2_carry_b, EdgeType.STRUCTURAL)
        g2o.add_edge(out2_carry_b, out2_carry_a, EdgeType.STRUCTURAL)

    return OperationDefinition(name=name, pattern=p, graph2s=g2s, graph2o=g2o)


# ---------------------------------------------------------------------------
# bit_add rules (8 rules)
# ---------------------------------------------------------------------------

def _make_bit_add_rule(left_bit: int, right_bit: int, carry_in: int) -> OperationDefinition:
    total = left_bit + right_bit + carry_in
    result_bit = total % 2
    carry_out = total >= 2
    name = f'bit_add_{left_bit}{right_bit}_c{carry_in}'

    # --- Pattern ---
    p = PerspectiveGraph()
    op_node, op_tag = _add_finished_op_node(p)
    left_pos = _add_bit_one(p) if left_bit else _add_bit_zero(p)
    right_pos = _add_bit_one(p) if right_bit else _add_bit_zero(p)
    left_parent = _add_parent(p, left_pos)
    right_parent = _add_parent(p, right_pos)
    p.add_edge(op_node, left_pos, EdgeType.OPERATIONAL)
    p.add_edge(op_node, right_pos, EdgeType.OPERATIONAL)
    result_node = _add_result_node(p, op_node)
    if carry_in:
        carry_a, carry_b = _add_carry(p, result_node)

    # --- graph2s ---
    # Input: clone of pattern with OPERATIONAL→STRUCTURAL
    g2s, p2g = _make_input_graph(p)
    in_op = p2g[op_node]
    in_cycles = [p2g[c] for c in op_tag.cycle_nodes]
    in_anchor = p2g[op_tag.anchor]
    in_left_parent = p2g[left_parent]
    in_right_parent = p2g[right_parent]
    in_result = p2g[result_node]
    # left_pos, right_pos, carry nodes: no output → deleted

    out_op = g2s.add_node()
    out_cycles = [g2s.add_node() for _ in op_tag.cycle_nodes]
    out_anchor = g2s.add_node()
    out_left_parent = g2s.add_node()
    out_right_parent = g2s.add_node()
    out_result = g2s.add_node()

    g2s.add_edge(in_op, out_op, EdgeType.OPERATIONAL)
    for ic, oc in zip(in_cycles, out_cycles):
        g2s.add_edge(ic, oc, EdgeType.OPERATIONAL)
    g2s.add_edge(in_anchor, out_anchor, EdgeType.OPERATIONAL)
    g2s.add_edge(in_left_parent, out_left_parent, EdgeType.OPERATIONAL)
    g2s.add_edge(in_right_parent, out_right_parent, EdgeType.OPERATIONAL)
    g2s.add_edge(in_result, out_result, EdgeType.OPERATIONAL)

    out_tag = OpTag(cycle_nodes=out_cycles, anchor=out_anchor, tail=None)
    _add_finished_tag_output(g2s, out_op, out_tag)
    g2s.add_edge(out_op, out_left_parent, EdgeType.STRUCTURAL)
    g2s.add_edge(out_op, out_right_parent, EdgeType.STRUCTURAL)
    g2s.add_edge(out_op, out_result, EdgeType.STRUCTURAL)
    if result_bit == 1:
        g2s.add_edge(out_result, out_result, EdgeType.STRUCTURAL)

    # --- graph2o ---
    # Build post-graph2s state
    post = PerspectiveGraph()
    post_op, post_op_tag = _add_finished_op_node(post)
    post_left_parent = post.add_node()
    post_right_parent = post.add_node()
    post_result = post.add_node()
    post.add_edge(post_op, post_left_parent, EdgeType.STRUCTURAL)
    post.add_edge(post_op, post_right_parent, EdgeType.STRUCTURAL)
    post.add_edge(post_op, post_result, EdgeType.STRUCTURAL)
    if result_bit == 1:
        post.add_edge(post_result, post_result, EdgeType.STRUCTURAL)

    g2o, post2g = _make_input_graph(post)
    in2_op = post2g[post_op]
    in2_left_parent = post2g[post_left_parent]
    in2_right_parent = post2g[post_right_parent]
    in2_result = post2g[post_result]

    out2_op = g2o.add_node()
    out2_left_parent = g2o.add_node()
    out2_right_parent = g2o.add_node()
    out2_result = g2o.add_node()

    g2o.add_edge(in2_op, out2_op, EdgeType.OPERATIONAL)
    g2o.add_edge(in2_left_parent, out2_left_parent, EdgeType.OPERATIONAL)
    g2o.add_edge(in2_right_parent, out2_right_parent, EdgeType.OPERATIONAL)
    g2o.add_edge(in2_result, out2_result, EdgeType.OPERATIONAL)

    out2_op_tag = OpTag(
        cycle_nodes=[g2o.add_node() for _ in post_op_tag.cycle_nodes],
        anchor=g2o.add_node(),
        tail=None,
    )
    _add_finished_tag_output(g2o, out2_op, out2_op_tag)
    g2o.add_edge(out2_op, out2_left_parent, EdgeType.STRUCTURAL)
    g2o.add_edge(out2_op, out2_right_parent, EdgeType.STRUCTURAL)
    g2o.add_edge(out2_op, out2_result, EdgeType.STRUCTURAL)

    g2o.add_edge(out2_op, out2_left_parent, EdgeType.OPERATIONAL)
    g2o.add_edge(out2_op, out2_right_parent, EdgeType.OPERATIONAL)
    g2o.add_edge(out2_op, out2_result, EdgeType.OPERATIONAL)
    if carry_out:
        out2_carry_a = g2o.add_node()
        out2_carry_b = g2o.add_node()
        g2o.add_edge(out2_result, out2_carry_a, EdgeType.OPERATIONAL)
        g2o.add_edge(out2_carry_a, out2_carry_b, EdgeType.STRUCTURAL)
        g2o.add_edge(out2_carry_b, out2_carry_a, EdgeType.STRUCTURAL)

    return OperationDefinition(name=name, pattern=p, graph2s=g2s, graph2o=g2o)


# ---------------------------------------------------------------------------
# drain rules (8 rules)
# ---------------------------------------------------------------------------

def _make_drain_rule(active_side: str, active_bit: int, carry_in: int) -> OperationDefinition:
    total = active_bit + carry_in
    result_bit = total % 2
    carry_out = total >= 2
    name = f'drain_{active_side}_{active_bit}_c{carry_in}'

    # --- Pattern ---
    p = PerspectiveGraph()
    op_node, op_tag = _add_finished_op_node(p)
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
        carry_a, carry_b = _add_carry(p, result_node)

    # --- graph2s ---
    g2s, p2g = _make_input_graph(p)
    in_op = p2g[op_node]
    in_cycles = [p2g[c] for c in op_tag.cycle_nodes]
    in_anchor = p2g[op_tag.anchor]
    in_active_parent = p2g[active_parent]
    in_exhausted = p2g[exhausted_pos]
    in_result = p2g[result_node]
    # active_pos, carry nodes: no output → deleted

    out_op = g2s.add_node()
    out_cycles = [g2s.add_node() for _ in op_tag.cycle_nodes]
    out_anchor = g2s.add_node()
    out_active_parent = g2s.add_node()
    out_exhausted = g2s.add_node()
    out_result = g2s.add_node()

    g2s.add_edge(in_op, out_op, EdgeType.OPERATIONAL)
    for ic, oc in zip(in_cycles, out_cycles):
        g2s.add_edge(ic, oc, EdgeType.OPERATIONAL)
    g2s.add_edge(in_anchor, out_anchor, EdgeType.OPERATIONAL)
    g2s.add_edge(in_active_parent, out_active_parent, EdgeType.OPERATIONAL)
    g2s.add_edge(in_exhausted, out_exhausted, EdgeType.OPERATIONAL)
    g2s.add_edge(in_result, out_result, EdgeType.OPERATIONAL)

    out_tag = OpTag(cycle_nodes=out_cycles, anchor=out_anchor, tail=None)
    _add_finished_tag_output(g2s, out_op, out_tag)
    if active_side == 'left':
        g2s.add_edge(out_op, out_active_parent, EdgeType.STRUCTURAL)
        g2s.add_edge(out_op, out_exhausted, EdgeType.STRUCTURAL)
    else:
        g2s.add_edge(out_op, out_exhausted, EdgeType.STRUCTURAL)
        g2s.add_edge(out_op, out_active_parent, EdgeType.STRUCTURAL)
    g2s.add_edge(out_op, out_result, EdgeType.STRUCTURAL)
    if result_bit == 1:
        g2s.add_edge(out_result, out_result, EdgeType.STRUCTURAL)

    # --- graph2o ---
    post = PerspectiveGraph()
    post_op, post_op_tag = _add_finished_op_node(post)
    post_active_parent = post.add_node()
    post_exhausted = post.add_node()
    post_result = post.add_node()
    if active_side == 'left':
        post.add_edge(post_op, post_active_parent, EdgeType.STRUCTURAL)
        post.add_edge(post_op, post_exhausted, EdgeType.STRUCTURAL)
    else:
        post.add_edge(post_op, post_exhausted, EdgeType.STRUCTURAL)
        post.add_edge(post_op, post_active_parent, EdgeType.STRUCTURAL)
    post.add_edge(post_op, post_result, EdgeType.STRUCTURAL)
    if result_bit == 1:
        post.add_edge(post_result, post_result, EdgeType.STRUCTURAL)

    g2o, post2g = _make_input_graph(post)
    in2_op = post2g[post_op]
    in2_active_parent = post2g[post_active_parent]
    in2_exhausted = post2g[post_exhausted]
    in2_result = post2g[post_result]

    out2_op = g2o.add_node()
    out2_active_parent = g2o.add_node()
    out2_exhausted = g2o.add_node()
    out2_result = g2o.add_node()

    g2o.add_edge(in2_op, out2_op, EdgeType.OPERATIONAL)
    g2o.add_edge(in2_active_parent, out2_active_parent, EdgeType.OPERATIONAL)
    g2o.add_edge(in2_exhausted, out2_exhausted, EdgeType.OPERATIONAL)
    g2o.add_edge(in2_result, out2_result, EdgeType.OPERATIONAL)

    out2_op_tag = OpTag(
        cycle_nodes=[g2o.add_node() for _ in post_op_tag.cycle_nodes],
        anchor=g2o.add_node(),
        tail=None,
    )
    _add_finished_tag_output(g2o, out2_op, out2_op_tag)
    if active_side == 'left':
        g2o.add_edge(out2_op, out2_active_parent, EdgeType.STRUCTURAL)
        g2o.add_edge(out2_op, out2_exhausted, EdgeType.STRUCTURAL)
    else:
        g2o.add_edge(out2_op, out2_exhausted, EdgeType.STRUCTURAL)
        g2o.add_edge(out2_op, out2_active_parent, EdgeType.STRUCTURAL)
    g2o.add_edge(out2_op, out2_result, EdgeType.STRUCTURAL)

    if active_side == 'left':
        g2o.add_edge(out2_op, out2_active_parent, EdgeType.OPERATIONAL)
        g2o.add_edge(out2_op, out2_exhausted, EdgeType.OPERATIONAL)
    else:
        g2o.add_edge(out2_op, out2_exhausted, EdgeType.OPERATIONAL)
        g2o.add_edge(out2_op, out2_active_parent, EdgeType.OPERATIONAL)
    g2o.add_edge(out2_op, out2_result, EdgeType.OPERATIONAL)
    if carry_out:
        out2_carry_a = g2o.add_node()
        out2_carry_b = g2o.add_node()
        g2o.add_edge(out2_result, out2_carry_a, EdgeType.OPERATIONAL)
        g2o.add_edge(out2_carry_a, out2_carry_b, EdgeType.STRUCTURAL)
        g2o.add_edge(out2_carry_b, out2_carry_a, EdgeType.STRUCTURAL)

    return OperationDefinition(name=name, pattern=p, graph2s=g2s, graph2o=g2o)


# ---------------------------------------------------------------------------
# add_finalise rules (8 rules)
# ---------------------------------------------------------------------------

def _make_add_finalise_rule(left_msb: int, right_msb: int, carry_in: int) -> OperationDefinition:
    total = left_msb + right_msb + carry_in
    result_bit = total % 2
    carry_out = total >= 2
    name = f'add_finalise_{left_msb}{right_msb}_c{carry_in}'

    # --- Pattern ---
    p = PerspectiveGraph()
    op_node, op_tag = _add_finished_op_node(p)
    left_pos = _add_bit_one(p) if left_msb else _add_bit_zero(p)
    right_pos = _add_bit_one(p) if right_msb else _add_bit_zero(p)
    p.add_edge(op_node, left_pos, EdgeType.OPERATIONAL)
    p.add_edge(op_node, right_pos, EdgeType.OPERATIONAL)
    result_node = _add_result_node(p, op_node)
    if carry_in:
        carry_a, carry_b = _add_carry(p, result_node)

    # --- graph2s ---
    # Op node survives bare (tag deleted — cycle/anchor have no output).
    # Result node survives. Left/right bits, carry, tag nodes: deleted.
    g2s, p2g = _make_input_graph(p)
    in_op = p2g[op_node]
    in_result = p2g[result_node]
    # All other pattern nodes: no output → deleted

    out_op = g2s.add_node()
    out_result = g2s.add_node()

    g2s.add_edge(in_op, out_op, EdgeType.OPERATIONAL)
    g2s.add_edge(in_result, out_result, EdgeType.OPERATIONAL)

    if result_bit == 1:
        g2s.add_edge(out_result, out_result, EdgeType.STRUCTURAL)
    if carry_out:
        out_msb = g2s.add_node()
        g2s.add_edge(out_msb, out_msb, EdgeType.STRUCTURAL)
        g2s.add_edge(out_op, out_msb, EdgeType.STRUCTURAL)
        g2s.add_edge(out_msb, out_result, EdgeType.STRUCTURAL)
    else:
        g2s.add_edge(out_op, out_result, EdgeType.STRUCTURAL)

    # --- graph2o ---
    # Empty — no operational edges to write.
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
