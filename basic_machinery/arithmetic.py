from __future__ import annotations
from basic_machinery.graph import PerspectiveGraph, Node, EdgeType
from basic_machinery.operations import OperationDefinition, MatchResult, register
from basic_machinery.encoding import build_number, build_operator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_deepest_right_leaf(graph: PerspectiveGraph, root: Node) -> Node:
    """
    Walk the right child (second structural child) of each internal node
    until a leaf is reached. Returns the deepest right leaf — the LSB.
    """
    current = root
    while True:
        struct_edges = graph.edges_from(current, EdgeType.STRUCTURAL)
        if not struct_edges:
            return current
        # Right child is the second structural edge added (index 1 if present)
        # For a leaf with self-loop, struct_edges has one self-loop — that is a leaf
        if len(struct_edges) == 1 and struct_edges[0].target == current:
            # Self-loop: this is a 1-leaf
            return current
        # Internal node: right child is second structural edge
        children = [e.target for e in struct_edges if e.target != current]
        if len(children) == 2:
            current = children[1]  # right child
        elif len(children) == 1:
            current = children[0]
        else:
            return current


def _get_position_nodes(graph: PerspectiveGraph, op_node: Node) -> tuple[Node, Node]:
    """
    Return (left_pos, right_pos) — the two position edge targets from op_node.
    Position edges are the 3rd and 4th operational edges (after left root, right root).
    """
    op_edges = graph.edges_from(op_node, EdgeType.OPERATIONAL)
    # First two are operand roots, next two are position pointers
    if len(op_edges) < 4:
        raise ValueError(f"Expected 4 operational edges on {op_node}, found {len(op_edges)}")
    return op_edges[2].target, op_edges[3].target


def _get_operand_roots(graph: PerspectiveGraph, op_node: Node) -> tuple[Node, Node]:
    op_edges = graph.edges_from(op_node, EdgeType.OPERATIONAL)
    return op_edges[0].target, op_edges[1].target


def _advance_position(graph: PerspectiveGraph, op_node: Node, pos_node: Node) -> None:
    """
    Move a position edge from pos_node to its parent in the binary tree.
    Parent is the node that has a structural edge pointing to pos_node.
    If no parent exists (pos_node is root), remove the position edge — signals exhaustion.
    """
    # Find the position edge
    pos_edge = next(
        e for e in graph.edges_from(op_node, EdgeType.OPERATIONAL)
        if e.target == pos_node
    )
    graph.remove_edge(pos_edge)

    # Find parent: node with structural edge to pos_node (excluding self-loops)
    parents = [
        e.source for e in graph.edges_to(pos_node, EdgeType.STRUCTURAL)
        if e.source != pos_node
    ]
    if parents:
        graph.add_edge(op_node, parents[0], EdgeType.OPERATIONAL)
    # If no parent: position edge removed, signals exhaustion for this operand


def _build_carry_marker(graph: PerspectiveGraph, op_node: Node) -> Node:
    """
    Attach a carry marker to op_node via structural edge.
    Shape: 2-cycle (two nodes pointing at each other).
    """
    a = graph.add_node()
    b = graph.add_node()
    graph.add_edge(a, b, EdgeType.STRUCTURAL)
    graph.add_edge(b, a, EdgeType.STRUCTURAL)
    graph.add_edge(op_node, a, EdgeType.STRUCTURAL)
    return a


def _remove_carry_marker(graph: PerspectiveGraph, op_node: Node) -> None:
    """
    Remove carry marker (2-cycle) attached to op_node via structural edge.
    """
    for e in graph.edges_from(op_node, EdgeType.STRUCTURAL):
        candidate = e.target
        # Check if candidate is part of a 2-cycle
        neighbors = graph.edges_from(candidate, EdgeType.STRUCTURAL)
        if len(neighbors) == 1 and neighbors[0].target != candidate:
            partner = neighbors[0].target
            back_edges = graph.edges_from(partner, EdgeType.STRUCTURAL)
            if len(back_edges) == 1 and back_edges[0].target == candidate:
                # Found 2-cycle: remove marker edge, both nodes
                graph.remove_edge(e)
                graph.remove_node(candidate)
                graph.remove_node(partner)
                return


def _has_carry(graph: PerspectiveGraph, op_node: Node) -> bool:
    for e in graph.edges_from(op_node, EdgeType.STRUCTURAL):
        candidate = e.target
        neighbors = graph.edges_from(candidate, EdgeType.STRUCTURAL)
        if len(neighbors) == 1 and neighbors[0].target != candidate:
            partner = neighbors[0].target
            back_edges = graph.edges_from(partner, EdgeType.STRUCTURAL)
            if len(back_edges) == 1 and back_edges[0].target == candidate:
                return True
    return False


def _is_empty_node(graph: PerspectiveGraph, node: Node) -> bool:
    """No structural edges at all — bit value 0."""
    return len(graph.edges_from(node, EdgeType.STRUCTURAL)) == 0


def _is_one_node(graph: PerspectiveGraph, node: Node) -> bool:
    """Single self-loop — bit value 1."""
    edges = graph.edges_from(node, EdgeType.STRUCTURAL)
    return len(edges) == 1 and edges[0].target == node


def _append_result_bit(graph: PerspectiveGraph, op_node: Node, bit: int) -> None:
    """
    Append a result bit node to the result tree on op_node.
    Result root is the 5th operational edge target if it exists.
    Result grows as a chain: each new bit node becomes the new result root,
    with a structural edge to the previous root (MSB direction).
    """
    result_edges = [
        e for e in graph.edges_from(op_node, EdgeType.OPERATIONAL)
        if _is_result_edge(graph, op_node, e)
    ]

    new_bit = graph.add_node()
    if bit == 1:
        graph.add_edge(new_bit, new_bit, EdgeType.STRUCTURAL)

    if result_edges:
        prev_root = result_edges[0].target
        graph.remove_edge(result_edges[0])
        graph.add_edge(new_bit, prev_root, EdgeType.STRUCTURAL)

    graph.add_edge(op_node, new_bit, EdgeType.OPERATIONAL)


def _is_result_edge(graph: PerspectiveGraph, op_node: Node, edge) -> bool:
    """
    Distinguish result edge from operand root edges and position edges.
    Operand roots: first two operational edges (stable).
    Position edges: point to nodes inside the operand trees.
    Result edge: points to a node NOT in either operand tree.
    """
    # Get operand roots
    op_edges = graph.edges_from(op_node, EdgeType.OPERATIONAL)
    if len(op_edges) < 2:
        return False
    operand_roots = {op_edges[0].target, op_edges[1].target}
    target = edge.target
    # If target is reachable from either operand root via structural edges, it's not result
    return not _reachable(graph, operand_roots, target)


def _reachable(graph: PerspectiveGraph, roots: set[Node], target: Node) -> bool:
    visited = set()
    stack = list(roots)
    while stack:
        node = stack.pop()
        if node == target:
            return True
        if node in visited:
            continue
        visited.add(node)
        for e in graph.edges_from(node, EdgeType.STRUCTURAL):
            if e.target not in visited:
                stack.append(e.target)
    return False


# ---------------------------------------------------------------------------
# add_init
# ---------------------------------------------------------------------------

def _add_init_pattern() -> PerspectiveGraph:
    """
    Pattern: a + operator node with its triangle tag.
    Match fires on any + node — rewrite checks operand edge count.
    """
    from basic_machinery.encoding import build_operator
    p = PerspectiveGraph()
    build_operator(p, '+')
    return p


def _add_init_rewrite(graph: PerspectiveGraph, result: MatchResult) -> None:
    # Find the + node in the match — the one with the triangle tag
    op_node = _find_plus_node(graph, result)
    if op_node is None:
        return

    op_edges = graph.edges_from(op_node, EdgeType.OPERATIONAL)
    # Only fire if exactly two operational edges (not yet initialised)
    if len(op_edges) != 2:
        return

    left_root, right_root = op_edges[0].target, op_edges[1].target
    left_lsb = _find_deepest_right_leaf(graph, left_root)
    right_lsb = _find_deepest_right_leaf(graph, right_root)

    graph.add_edge(op_node, left_lsb, EdgeType.OPERATIONAL)
    graph.add_edge(op_node, right_lsb, EdgeType.OPERATIONAL)


def _find_plus_node(graph: PerspectiveGraph, result: MatchResult) -> Node | None:
    """
    From the match result, find the node that has a triangle structural tag
    (3-cycle attached) — that is the + operator node.
    """
    for node in result.node_map.values():
        struct_edges = graph.edges_from(node, EdgeType.STRUCTURAL)
        targets = [e.target for e in struct_edges]
        # + node points to first cycle node; cycle node is not self and has no self-loop
        if len(targets) == 1 and targets[0] != node:
            cycle_start = targets[0]
            # Check it's part of a 3-cycle
            if _is_n_cycle_start(graph, cycle_start, 3):
                return node
    return None


def _is_n_cycle_start(graph: PerspectiveGraph, node: Node, n: int) -> bool:
    current = node
    for _ in range(n):
        edges = graph.edges_from(current, EdgeType.STRUCTURAL)
        if len(edges) != 1:
            return False
        current = edges[0].target
    return current == node


# ---------------------------------------------------------------------------
# Bit rules
# ---------------------------------------------------------------------------

def _bit_step(
    graph: PerspectiveGraph,
    op_node: Node,
    left_pos: Node,
    right_pos: Node,
    carry_in: bool
) -> None:
    """
    Core bit addition logic. Computes result bit and carry out.
    Appends result bit, advances positions, updates carry marker.
    """
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
    elif not carry_out and carry_in:
        _remove_carry_marker(graph, op_node)


def _make_bit_rule_pattern(left_bit: int, right_bit: int) -> PerspectiveGraph:
    """
    Pattern: + node with triangle tag only.
    Bit values checked dynamically in rewrite — pattern topology alone
    cannot encode specific bit node shapes relative to position pointers
    without variable-depth path matching.
    """
    return _add_init_pattern()


def _bit_rule_rewrite(
    graph: PerspectiveGraph,
    result: MatchResult,
    expect_left: int,
    expect_right: int,
    carry_in: bool
) -> None:
    op_node = _find_plus_node(graph, result)
    if op_node is None:
        return

    op_edges = graph.edges_from(op_node, EdgeType.OPERATIONAL)
    # Must have 4 operational edges (2 roots + 2 positions)
    if len(op_edges) < 4:
        return

    left_pos, right_pos = op_edges[2].target, op_edges[3].target

    # Check carry state matches expectation
    if _has_carry(graph, op_node) != carry_in:
        return

    # Check bit values match
    left_actual = 1 if _is_one_node(graph, left_pos) else 0
    right_actual = 1 if _is_one_node(graph, right_pos) else 0
    if left_actual != expect_left or right_actual != expect_right:
        return

    _bit_step(graph, op_node, left_pos, right_pos, carry_in)


# ---------------------------------------------------------------------------
# add_finalise
# ---------------------------------------------------------------------------

def _add_finalise_rewrite(graph: PerspectiveGraph, result: MatchResult) -> None:
    op_node = _find_plus_node(graph, result)
    if op_node is None:
        return

    op_edges = graph.edges_from(op_node, EdgeType.OPERATIONAL)
    # Finalise when exactly one operational edge remains — the result root
    if len(op_edges) != 1:
        return
    if _has_carry(graph, op_node):
        # Append final carry bit
        _append_result_bit(graph, op_node, 1)

    result_root = graph.edges_from(op_node, EdgeType.OPERATIONAL)[0].target

    # Rewire parent to result root
    incoming = graph.edges_to(op_node)
    for e in incoming:
        graph.add_edge(e.source, result_root, e.edge_type)
        graph.remove_edge(e)

    graph.remove_node(op_node)


# ---------------------------------------------------------------------------
# Garbage collection
# ---------------------------------------------------------------------------

def _garbage_collect(graph: PerspectiveGraph) -> None:
    """
    Remove all nodes with no incoming edges that are not reachable
    from any operator or equality node. Iterates until stable.
    """
    changed = True
    while changed:
        changed = False
        for node in list(graph.nodes):
            incoming = graph.edges_to(node)
            if not incoming:
                graph.remove_node(node)
                changed = True


# ---------------------------------------------------------------------------
# Register rules
# ---------------------------------------------------------------------------

_p_init = _add_init_pattern()
register(OperationDefinition(
    name='add_init',
    pattern=_p_init,
    rewrite=_add_init_rewrite
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
    _p = _make_bit_rule_pattern(_left, _right)
    register(OperationDefinition(
        name=_name,
        pattern=_p,
        rewrite=lambda g, r, l=_left, ri=_right, c=_carry: _bit_rule_rewrite(g, r, l, ri, c)
    ))

register(OperationDefinition(
    name='add_finalise',
    pattern=_add_init_pattern(),
    rewrite=_add_finalise_rewrite
))