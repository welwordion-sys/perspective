from __future__ import annotations
from basic_machinery.graph import PerspectiveGraph, Node, EdgeType
from basic_machinery.operations import OperationDefinition, MatchResult, register


# ---------------------------------------------------------------------------
# Carry marker helpers — 2-cycle attached via structural edge from op node
# ---------------------------------------------------------------------------

def _build_carry_marker(graph: PerspectiveGraph, op_node: Node) -> None:
    a = graph.add_node()
    b = graph.add_node()
    graph.add_edge(a, b, EdgeType.STRUCTURAL)
    graph.add_edge(b, a, EdgeType.STRUCTURAL)
    graph.add_edge(op_node, a, EdgeType.STRUCTURAL)


def _has_carry(graph: PerspectiveGraph, op_node: Node) -> bool:
    for e in graph.edges_from(op_node, EdgeType.STRUCTURAL):
        candidate = e.target
        if candidate == op_node:
            continue
        out = graph.edges_from(candidate, EdgeType.STRUCTURAL)
        if len(out) == 1 and out[0].target != candidate:
            partner = out[0].target
            back = graph.edges_from(partner, EdgeType.STRUCTURAL)
            if len(back) == 1 and back[0].target == candidate:
                return True
    return False


def _remove_carry_marker(graph: PerspectiveGraph, op_node: Node) -> None:
    for e in graph.edges_from(op_node, EdgeType.STRUCTURAL):
        candidate = e.target
        if candidate == op_node:
            continue
        out = graph.edges_from(candidate, EdgeType.STRUCTURAL)
        if len(out) == 1 and out[0].target != candidate:
            partner = out[0].target
            back = graph.edges_from(partner, EdgeType.STRUCTURAL)
            if len(back) == 1 and back[0].target == candidate:
                graph.remove_edge(e)
                graph.remove_node(candidate)
                graph.remove_node(partner)
                return


# ---------------------------------------------------------------------------
# Tombstone helpers — 3-node chain: node -> a -> b (no cycles, no self-loops)
# ---------------------------------------------------------------------------

def _build_tombstone(graph: PerspectiveGraph, target: Node) -> None:
    a = graph.add_node()
    b = graph.add_node()
    graph.add_edge(a, b, EdgeType.STRUCTURAL)
    graph.add_edge(target, a, EdgeType.STRUCTURAL)


def _find_tombstone_chain(
    graph: PerspectiveGraph, node: Node
) -> tuple[Node, Node] | None:
    """
    Return (a, b) if node has a tombstone chain node->a->b attached,
    where a and b are plain nodes with no other structural edges.
    Returns None if no tombstone found.
    """
    for e in graph.edges_from(node, EdgeType.STRUCTURAL):
        a = e.target
        if a == node:
            continue
        a_out = graph.edges_from(a, EdgeType.STRUCTURAL)
        if len(a_out) == 1:
            b = a_out[0].target
            if b == a or b == node:
                continue
            b_out = graph.edges_from(b, EdgeType.STRUCTURAL)
            if len(b_out) == 0:
                return a, b
    return None


def _is_tombstoned(graph: PerspectiveGraph, node: Node) -> bool:
    return _find_tombstone_chain(graph, node) is not None


def _remove_tombstone(graph: PerspectiveGraph, node: Node) -> None:
    chain = _find_tombstone_chain(graph, node)
    if chain is None:
        return
    a, b = chain
    tomb_edge = next(
        e for e in graph.edges_from(node, EdgeType.STRUCTURAL)
        if e.target == a
    )
    graph.remove_edge(tomb_edge)
    graph.remove_node(b)
    graph.remove_node(a)


# ---------------------------------------------------------------------------
# Bit node helpers
# ---------------------------------------------------------------------------

def _is_empty_node(graph: PerspectiveGraph, node: Node) -> bool:
    return len(graph.edges_from(node, EdgeType.STRUCTURAL)) == 0


def _is_one_node(graph: PerspectiveGraph, node: Node) -> bool:
    edges = graph.edges_from(node, EdgeType.STRUCTURAL)
    return len(edges) == 1 and edges[0].target == node


# ---------------------------------------------------------------------------
# Operator node helpers
# ---------------------------------------------------------------------------

def _is_n_cycle_start(graph: PerspectiveGraph, node: Node, n: int) -> bool:
    current = node
    for _ in range(n):
        edges = graph.edges_from(current, EdgeType.STRUCTURAL)
        if len(edges) != 1:
            return False
        current = edges[0].target
    return current == node


def _find_plus_node(graph: PerspectiveGraph, result: MatchResult) -> Node | None:
    for mapped in result.node_map.values():
        for e in graph.edges_from(mapped, EdgeType.STRUCTURAL):
            if e.target == mapped:
                continue
            if _is_n_cycle_start(graph, e.target, 3):
                return mapped
    return None


# ---------------------------------------------------------------------------
# Tree traversal helpers
# ---------------------------------------------------------------------------

def _find_deepest_right_leaf(graph: PerspectiveGraph, root: Node) -> Node:
    """
    Walk structural children toward the deepest right leaf (LSB).
    Right child = second structural child (non-self-loop).
    Leaf = node with no non-self-loop structural children.
    """
    current = root
    while True:
        children = [
            e.target for e in graph.edges_from(current, EdgeType.STRUCTURAL)
            if e.target != current
        ]
        if not children:
            return current
        # Right child is index 1 if two children, index 0 if one
        current = children[1] if len(children) >= 2 else children[0]


def _get_parent(graph: PerspectiveGraph, node: Node) -> Node | None:
    """
    Return the parent of node in the binary tree — the node with a
    structural edge to this node, excluding self-loops.
    """
    parents = [
        e.source for e in graph.edges_to(node, EdgeType.STRUCTURAL)
        if e.source != node
    ]
    return parents[0] if parents else None


# ---------------------------------------------------------------------------
# Position edge helpers
# ---------------------------------------------------------------------------

def _get_position_nodes(
    graph: PerspectiveGraph, op_node: Node
) -> tuple[Node, Node] | None:
    """
    Return (left_pos, right_pos) — operational edges 3 and 4 from op_node.
    Returns None if fewer than 4 operational edges exist.
    """
    op_edges = graph.edges_from(op_node, EdgeType.OPERATIONAL)
    if len(op_edges) < 4:
        return None
    return op_edges[2].target, op_edges[3].target


def _advance_position(
    graph: PerspectiveGraph, op_node: Node, pos_node: Node
) -> None:
    """
    Move position edge from pos_node to its parent.
    If no parent (pos_node is root / MSB), remove edge — signals exhaustion.
    """
    pos_edge = next(
        e for e in graph.edges_from(op_node, EdgeType.OPERATIONAL)
        if e.target == pos_node
    )
    graph.remove_edge(pos_edge)
    parent = _get_parent(graph, pos_node)
    if parent is not None:
        graph.add_edge(op_node, parent, EdgeType.OPERATIONAL)


# ---------------------------------------------------------------------------
# Result tree helpers
# ---------------------------------------------------------------------------

def _get_operand_roots(graph: PerspectiveGraph, op_node: Node) -> tuple[Node, Node]:
    op_edges = graph.edges_from(op_node, EdgeType.OPERATIONAL)
    return op_edges[0].target, op_edges[1].target


def _in_operand_trees(
    graph: PerspectiveGraph, op_node: Node, target: Node
) -> bool:
    left_root, right_root = _get_operand_roots(graph, op_node)
    visited: set[Node] = set()
    stack = [left_root, right_root]
    while stack:
        node = stack.pop()
        if node == target:
            return True
        if node in visited:
            continue
        visited.add(node)
        for e in graph.edges_from(node, EdgeType.STRUCTURAL):
            stack.append(e.target)
    return False


def _get_result_root(graph: PerspectiveGraph, op_node: Node) -> Node | None:
    op_edges = graph.edges_from(op_node, EdgeType.OPERATIONAL)
    for e in op_edges:
        if not _in_operand_trees(graph, op_node, e.target):
            return e.target
    return None


def _append_result_bit(
    graph: PerspectiveGraph, op_node: Node, bit: int
) -> None:
    """
    Append a result bit to the result tree.
    New bit node becomes new result root; previous root becomes its left child.
    Result tree grows MSB-toward-root as bits are appended LSB-first.
    """
    new_bit = graph.add_node()
    if bit == 1:
        graph.add_edge(new_bit, new_bit, EdgeType.STRUCTURAL)

    prev_root = _get_result_root(graph, op_node)
    if prev_root is not None:
        # Remove old result edge, attach new bit as new root
        old_edge = next(
            e for e in graph.edges_from(op_node, EdgeType.OPERATIONAL)
            if e.target == prev_root
        )
        graph.remove_edge(old_edge)
        graph.add_edge(new_bit, prev_root, EdgeType.STRUCTURAL)

    graph.add_edge(op_node, new_bit, EdgeType.OPERATIONAL)


# ---------------------------------------------------------------------------
# Core bit step
# ---------------------------------------------------------------------------

def _bit_step(
    graph: PerspectiveGraph,
    op_node: Node,
    left_pos: Node,
    right_pos: Node,
    carry_in: bool,
) -> None:
    left_bit = 1 if _is_one_node(graph, left_pos) else 0
    right_bit = 1 if _is_one_node(graph, right_pos) else 0
    total = left_bit + right_bit + (1 if carry_in else 0)
    result_bit = total % 2
    carry_out = total >= 2

    _append_result_bit(graph, op_node, result_bit)
    _advance_position(graph, op_node, left_pos)
    _advance_position(graph, op_node, right_pos)

    if carry_out and not carry_in:
        _build_carry_marker(graph, op_node)
    elif not carry_in and not carry_out:
        pass  # no change
    elif carry_in and not carry_out:
        _remove_carry_marker(graph, op_node)
    # carry_in and carry_out: marker stays, no change needed


# ---------------------------------------------------------------------------
# add_init
# ---------------------------------------------------------------------------

def _add_init_rewrite(graph: PerspectiveGraph, result: MatchResult) -> None:
    op_node = _find_plus_node(graph, result)
    if op_node is None:
        return
    # Only fire if exactly two operational edges — not yet initialised
    if len(graph.edges_from(op_node, EdgeType.OPERATIONAL)) != 2:
        return

    left_root, right_root = _get_operand_roots(graph, op_node)
    left_lsb = _find_deepest_right_leaf(graph, left_root)
    right_lsb = _find_deepest_right_leaf(graph, right_root)

    graph.add_edge(op_node, left_lsb, EdgeType.OPERATIONAL)
    graph.add_edge(op_node, right_lsb, EdgeType.OPERATIONAL)


# ---------------------------------------------------------------------------
# Bit rules
# ---------------------------------------------------------------------------

def _make_plus_pattern() -> PerspectiveGraph:
    from basic_machinery.encoding import build_operator
    p = PerspectiveGraph()
    build_operator(p, '+')
    return p


def _bit_rule_rewrite(
    graph: PerspectiveGraph,
    result: MatchResult,
    expect_left: int,
    expect_right: int,
    carry_in: bool,
) -> None:
    op_node = _find_plus_node(graph, result)
    if op_node is None:
        return

    positions = _get_position_nodes(graph, op_node)
    if positions is None:
        return

    left_pos, right_pos = positions

    if _has_carry(graph, op_node) != carry_in:
        return

    # Handle unequal operand lengths — exhausted side reads as 0
    left_actual = 1 if _is_one_node(graph, left_pos) else 0
    right_actual = 1 if _is_one_node(graph, right_pos) else 0

    if left_actual != expect_left or right_actual != expect_right:
        return

    _bit_step(graph, op_node, left_pos, right_pos, carry_in)


# ---------------------------------------------------------------------------
# Unequal length handling
# ---------------------------------------------------------------------------

def _drain_remaining_rewrite(graph: PerspectiveGraph, result: MatchResult) -> None:
    """
    Fires when one position is exhausted (only 3 operational edges remain)
    but the other still has a position. Drains remaining bits with implicit zero.
    """
    op_node = _find_plus_node(graph, result)
    if op_node is None:
        return

    op_edges = graph.edges_from(op_node, EdgeType.OPERATIONAL)
    # 3 edges: left root, right root, one remaining position
    if len(op_edges) != 3:
        return

    left_root, right_root = _get_operand_roots(graph, op_node)
    remaining_pos = next(
        e.target for e in op_edges
        if e.target != left_root and e.target != right_root
    )

    carry_in = _has_carry(graph, op_node)
    pos_bit = 1 if _is_one_node(graph, remaining_pos) else 0
    total = pos_bit + (1 if carry_in else 0)
    result_bit = total % 2
    carry_out = total >= 2

    _append_result_bit(graph, op_node, result_bit)
    _advance_position(graph, op_node, remaining_pos)

    if carry_out and not carry_in:
        _build_carry_marker(graph, op_node)
    elif carry_in and not carry_out:
        _remove_carry_marker(graph, op_node)


# ---------------------------------------------------------------------------
# add_finalise
# ---------------------------------------------------------------------------

def _add_finalise_rewrite(graph: PerspectiveGraph, result: MatchResult) -> None:
    op_node = _find_plus_node(graph, result)
    if op_node is None:
        return

    op_edges = graph.edges_from(op_node, EdgeType.OPERATIONAL)
    # Finalise when exactly 2 operational edges remain: left root, right root
    # (both position edges exhausted, result edge present separately)
    # Actually: 3 edges — left root, right root, result root
    if len(op_edges) != 3:
        return

    result_root = _get_result_root(graph, op_node)
    if result_root is None:
        return

    # Append final carry bit if carry still active
    if _has_carry(graph, op_node):
        _append_result_bit(graph, op_node, 1)
        _remove_carry_marker(graph, op_node)
        result_root = _get_result_root(graph, op_node)

    # Rewire parent to result root
    for e in list(graph.edges_to(op_node)):
        graph.add_edge(e.source, result_root, e.edge_type)
        graph.remove_edge(e)

    # Tombstone operand roots
    left_root, right_root = _get_operand_roots(graph, op_node)
    _build_tombstone(graph, left_root)
    _build_tombstone(graph, right_root)

    graph.remove_node(op_node)


# ---------------------------------------------------------------------------
# Tombstone GC rule
# ---------------------------------------------------------------------------

def _make_tombstone_pattern() -> PerspectiveGraph:
    """Pattern: node -> a -> b (3-node chain, no cycles)."""
    p = PerspectiveGraph()
    node = p.add_node()
    a = p.add_node()
    b = p.add_node()
    p.add_edge(node, a, EdgeType.STRUCTURAL)
    p.add_edge(a, b, EdgeType.STRUCTURAL)
    return p


def _tombstone_gc_rewrite(graph: PerspectiveGraph, result: MatchResult) -> None:
    """
    Find tombstoned node. Remove tombstone, attach tombstones to its
    structural children, then remove the node. Fires until subtree consumed.
    """
    tombstoned_node = None
    for mapped in result.node_map.values():
        chain = _find_tombstone_chain(graph, mapped)
        if chain is not None:
            tombstoned_node = mapped
            break

    if tombstoned_node is None:
        return

    # Collect structural children before removal (exclude tombstone chain nodes)
    chain = _find_tombstone_chain(graph, tombstoned_node)
    chain_nodes = set(chain) if chain else set()
    children = [
        e.target for e in graph.edges_from(tombstoned_node, EdgeType.STRUCTURAL)
        if e.target != tombstoned_node and e.target not in chain_nodes
    ]

    _remove_tombstone(graph, tombstoned_node)

    for child in children:
        _build_tombstone(graph, child)

    graph.remove_node(tombstoned_node)


# ---------------------------------------------------------------------------
# Register all rules
# ---------------------------------------------------------------------------

_p_plus = _make_plus_pattern()

register(OperationDefinition(
    name='add_init',
    pattern=_p_plus,
    rewrite=_add_init_rewrite,
))

for _left, _right, _carry in [
    (0, 0, False),
    (0, 1, False),
    (1, 0, False),
    (1, 1, False),
    (0, 0, True),
    (0, 1, True),
    (1, 0, True),
    (1, 1, True),
]:
    _name = f"bit_add_{_left}{_right}_{'c1' if _carry else 'c0'}"
    register(OperationDefinition(
        name=_name,
        pattern=_p_plus,
        rewrite=lambda g, r, l=_left, ri=_right, c=_carry: (
            _bit_rule_rewrite(g, r, l, ri, c)
        ),
    ))

register(OperationDefinition(
    name='drain_remaining',
    pattern=_p_plus,
    rewrite=_drain_remaining_rewrite,
))

register(OperationDefinition(
    name='add_finalise',
    pattern=_p_plus,
    rewrite=_add_finalise_rewrite,
))

register(OperationDefinition(
    name='tombstone_gc',
    pattern=_make_tombstone_pattern(),
    rewrite=_tombstone_gc_rewrite,
))