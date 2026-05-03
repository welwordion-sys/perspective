from __future__ import annotations
from basic_machinery.graph import PerspectiveGraph, Node, EdgeType
from basic_machinery.operations import OperationDefinition, register, MatchResult


# ---------------------------------------------------------------------------
# Tag builders — one per structural family
# ---------------------------------------------------------------------------

def _tag_zero(graph: PerspectiveGraph, node: Node) -> None:
    """Zero: empty node, no tag edges."""
    pass


def _tag_one(graph: PerspectiveGraph, node: Node) -> None:
    """One: single self-loop."""
    graph.add_edge(node, node, EdgeType.STRUCTURAL)


def _tag_parameter(graph: PerspectiveGraph, node: Node) -> None:
    """Parameter (x, y): bidirectional edge to a dedicated companion node."""
    companion = graph.add_node()
    graph.add_edge(node, companion, EdgeType.STRUCTURAL)
    graph.add_edge(companion, node, EdgeType.STRUCTURAL)


def _tag_cycle(graph: PerspectiveGraph, node: Node, size: int) -> None:
    """
    Attach a directed cycle of `size` nodes to `node`.
    node -> cycle[0] -> cycle[1] -> ... -> cycle[size-1] -> cycle[0]
    """
    cycle_nodes = [graph.add_node() for _ in range(size)]
    for i in range(size):
        graph.add_edge(cycle_nodes[i], cycle_nodes[(i + 1) % size], EdgeType.STRUCTURAL)
    graph.add_edge(node, cycle_nodes[0], EdgeType.STRUCTURAL)


def _tag_cycle_plus(graph: PerspectiveGraph, node: Node, size: int) -> None:
    """
    Attach a directed cycle of `size` nodes plus one tail node.
    node -> cycle[0] -> ... -> cycle[size-1] -> cycle[0]
                               cycle[size-1] -> tail
    """
    cycle_nodes = [graph.add_node() for _ in range(size)]
    tail = graph.add_node()
    for i in range(size - 1):
        graph.add_edge(cycle_nodes[i], cycle_nodes[i + 1], EdgeType.STRUCTURAL)
    graph.add_edge(cycle_nodes[-1], cycle_nodes[0], EdgeType.STRUCTURAL)
    graph.add_edge(cycle_nodes[-1], tail, EdgeType.STRUCTURAL)
    graph.add_edge(node, cycle_nodes[0], EdgeType.STRUCTURAL)


# ---------------------------------------------------------------------------
# Operator and equality node builders
# ---------------------------------------------------------------------------

_OPERATOR_TAGS = {
    '+': (_tag_cycle,      3),  # triangle
    '-': (_tag_cycle_plus, 3),  # triangle + tail
    '*': (_tag_cycle,      4),  # square
    '/': (_tag_cycle_plus, 4),  # square + tail
}

_EQUALITY_TAGS = {
    'unfinished': (_tag_cycle,      5),
    'finished':   (_tag_cycle_plus, 5),
}


def build_operator(graph: PerspectiveGraph, op: str) -> Node:
    """Build an operator node with its identifying cycle tag. Returns the operator node."""
    if op not in _OPERATOR_TAGS:
        raise ValueError(f"Unknown operator '{op}'. Expected one of {list(_OPERATOR_TAGS)}")
    node = graph.add_node()
    tag_fn, size = _OPERATOR_TAGS[op]
    tag_fn(graph, node, size)
    return node


def build_equality(graph: PerspectiveGraph, finished: bool = False) -> Node:
    """
    Build an equality node.
    Unfinished (default): open equation, at least one parameter side.
    Finished: both sides are concrete values — terminal state, no rules fire on this.
    """
    node = graph.add_node()
    tag_fn, size = _EQUALITY_TAGS['finished' if finished else 'unfinished']
    tag_fn(graph, node, size)
    return node


# ---------------------------------------------------------------------------
# Number encoding
# ---------------------------------------------------------------------------

def build_number(graph: PerspectiveGraph, value: int) -> Node:
    """
    Encode a non-negative integer as an open-length binary tree.
    Bit order: MSB at root, LSB at deepest right leaf.
    Leaf nodes: empty node = 0, self-loop node = 1.
    Internal nodes: two structural children (left = higher bits, right = current bit).
    Returns the root node.
    """
    if value < 0:
        raise ValueError("build_number does not handle negative integers.")
    bits = bin(value)[2:]  # e.g. 6 -> '110'
    return _build_bit_tree(graph, bits)


def _build_bit_tree(graph: PerspectiveGraph, bits: str) -> Node:
    node = graph.add_node()
    if len(bits) == 1:
        if bits == '1':
            _tag_one(graph, node)
        # bits == '0': empty node, _tag_zero is a no-op
    else:
        left = _build_bit_tree(graph, bits[:-1])  # higher bits
        right = _build_bit_tree(graph, bits[-1])  # current LSB
        graph.add_edge(node, left, EdgeType.STRUCTURAL)
        graph.add_edge(node, right, EdgeType.STRUCTURAL)
    return node


# ---------------------------------------------------------------------------
# Parameter encoding
# ---------------------------------------------------------------------------

def build_parameter(graph: PerspectiveGraph) -> Node:
    """
    Encode a symbolic parameter (x, y, ...).
    Shape: bidirectional edge to a dedicated companion node.
    All parameters are structurally identical — identity from position
    in the expression tree, not from the node itself.
    Returns the parameter node.
    """
    node = graph.add_node()
    _tag_parameter(graph, node)
    return node


# ---------------------------------------------------------------------------
# Expression assembly
# ---------------------------------------------------------------------------

def connect_operands(
    graph: PerspectiveGraph,
    op_node: Node,
    left_root: Node,
    right_root: Node
) -> None:
    """
    Connect an operator node to its two operand subtree roots
    via operational edges. Left operand first, right operand second.
    """
    graph.add_edge(op_node, left_root, EdgeType.OPERATIONAL)
    graph.add_edge(op_node, right_root, EdgeType.OPERATIONAL)


def connect_equality(
    graph: PerspectiveGraph,
    eq_node: Node,
    left_root: Node,
    right_root: Node
) -> None:
    """
    Connect an equality node to the roots of its left and right
    expression subtrees via operational edges.
    """
    graph.add_edge(eq_node, left_root, EdgeType.OPERATIONAL)
    graph.add_edge(eq_node, right_root, EdgeType.OPERATIONAL)


def get_operands(graph: PerspectiveGraph, op_node: Node) -> tuple[Node, Node]:
    """
    Return the (left, right) operand roots of an operator or equality node.
    Order matches the order operational edges were added.
    Raises if the node does not have exactly two operational edges.
    """
    edges = graph.edges_from(op_node, EdgeType.OPERATIONAL)
    if len(edges) != 2:
        raise ValueError(
            f"Expected 2 operational edges from {op_node}, found {len(edges)}."
        )
    return edges[0].target, edges[1].target


# ---------------------------------------------------------------------------
# Expression parser and encoder
# ---------------------------------------------------------------------------

def encode(graph: PerspectiveGraph, expression: str) -> Node:
    """
    Parse a simple arithmetic expression or linear equation and encode it
    into the graph. Returns the root node of the encoded structure.

    Supported syntax:
      - Non-negative integers: 0, 1, 42, ...
      - Single parameter: x
      - Binary operators: +, -, *, /
      - Equality: = (produces an unfinished equality node)
      - Parentheses for explicit grouping

    Examples:
      encode(g, "3 + 4")
      encode(g, "x + 4 = 7")
      encode(g, "2 * x + 4 = 10")
    """
    tokens = _tokenize(expression)
    node, pos = _parse_equality(graph, tokens, 0)
    if pos != len(tokens):
        raise ValueError(f"Unexpected token at position {pos}: '{tokens[pos]}'")
    return node


def _tokenize(expression: str) -> list[str]:
    tokens = []
    i = 0
    s = expression.replace(' ', '')
    while i < len(s):
        if s[i].isdigit():
            j = i
            while j < len(s) and s[j].isdigit():
                j += 1
            tokens.append(s[i:j])
            i = j
        elif s[i] in '+-*/()=x':
            tokens.append(s[i])
            i += 1
        else:
            raise ValueError(f"Unknown character '{s[i]}' in expression.")
    return tokens


def _parse_equality(
    graph: PerspectiveGraph, tokens: list[str], pos: int
) -> tuple[Node, int]:
    left, pos = _parse_additive(graph, tokens, pos)
    if pos < len(tokens) and tokens[pos] == '=':
        pos += 1
        right, pos = _parse_additive(graph, tokens, pos)
        eq_node = build_equality(graph, finished=False)
        connect_equality(graph, eq_node, left, right)
        return eq_node, pos
    return left, pos


def _parse_additive(
    graph: PerspectiveGraph, tokens: list[str], pos: int
) -> tuple[Node, int]:
    left, pos = _parse_multiplicative(graph, tokens, pos)
    while pos < len(tokens) and tokens[pos] in ('+', '-'):
        op = tokens[pos]
        pos += 1
        right, pos = _parse_multiplicative(graph, tokens, pos)
        op_node = build_operator(graph, op)
        connect_operands(graph, op_node, left, right)
        left = op_node
    return left, pos


def _parse_multiplicative(
    graph: PerspectiveGraph, tokens: list[str], pos: int
) -> tuple[Node, int]:
    left, pos = _parse_primary(graph, tokens, pos)
    while pos < len(tokens) and tokens[pos] in ('*', '/'):
        op = tokens[pos]
        pos += 1
        right, pos = _parse_primary(graph, tokens, pos)
        op_node = build_operator(graph, op)
        connect_operands(graph, op_node, left, right)
        left = op_node
    return left, pos


def _parse_primary(
    graph: PerspectiveGraph, tokens: list[str], pos: int
) -> tuple[Node, int]:
    if pos >= len(tokens):
        raise ValueError("Unexpected end of expression.")
    token = tokens[pos]
    if token == '(':
        node, pos = _parse_equality(graph, tokens, pos + 1)
        if pos >= len(tokens) or tokens[pos] != ')':
            raise ValueError("Expected closing parenthesis.")
        return node, pos + 1
    if token == 'x':
        return build_parameter(graph), pos + 1
    if token.isdigit() or (len(token) > 1 and token.isdigit()):
        return build_number(graph, int(token)), pos + 1
    raise ValueError(f"Unexpected token '{token}' at position {pos}.")


# ---------------------------------------------------------------------------
# Seed rules
# ---------------------------------------------------------------------------

def _make_add_zero_pattern() -> tuple[PerspectiveGraph, Node, Node]:
    """
    Pattern: an addition node with a zero node as one operand.
    Returns (pattern_graph, add_node, zero_node).
    The second operand is not in the pattern — recovered dynamically in rewrite.
    """
    p = PerspectiveGraph()
    add_node = build_operator(p, '+')
    zero_node = build_number(p, 0)
    p.add_edge(add_node, zero_node, EdgeType.OPERATIONAL)
    return p, add_node, zero_node


def _make_mul_one_pattern() -> tuple[PerspectiveGraph, Node, Node]:
    """Pattern: a multiplication node with a one node as one operand."""
    p = PerspectiveGraph()
    mul_node = build_operator(p, '*')
    one_node = build_number(p, 1)
    p.add_edge(mul_node, one_node, EdgeType.OPERATIONAL)
    return p, mul_node, one_node


def _make_sub_zero_pattern() -> tuple[PerspectiveGraph, Node, Node]:
    """Pattern: a subtraction node with a zero node as right operand."""
    p = PerspectiveGraph()
    sub_node = build_operator(p, '-')
    zero_node = build_number(p, 0)
    p.add_edge(sub_node, zero_node, EdgeType.OPERATIONAL)
    return p, sub_node, zero_node


def _make_div_one_pattern() -> tuple[PerspectiveGraph, Node, Node]:
    """Pattern: a division node with a one node as right operand."""
    p = PerspectiveGraph()
    div_node = build_operator(p, '/')
    one_node = build_number(p, 1)
    p.add_edge(div_node, one_node, EdgeType.OPERATIONAL)
    return p, div_node, one_node


def _make_mul_zero_pattern() -> tuple[PerspectiveGraph, Node, Node]:
    """Pattern: a multiplication node with a zero node as one operand."""
    p = PerspectiveGraph()
    mul_node = build_operator(p, '*')
    zero_node = build_number(p, 0)
    p.add_edge(mul_node, zero_node, EdgeType.OPERATIONAL)
    return p, mul_node, zero_node


def _neutral_element_rewrite(
    graph: PerspectiveGraph,
    result: MatchResult,
    pattern_op: Node,
    pattern_neutral: Node
) -> None:
    """
    Generic rewrite for neutral element collapse.
    Finds the surviving operand (the one that is NOT the neutral element),
    rewires any edges pointing to the operator node to point to the survivor,
    then removes the operator node and neutral subtree.
    """
    graph_op = result.node_map[pattern_op]
    graph_neutral = result.node_map[pattern_neutral]

    # Find the surviving operand root
    op_edges = graph.edges_from(graph_op, EdgeType.OPERATIONAL)
    survivor = None
    for e in op_edges:
        if e.target != graph_neutral:
            survivor = e.target
            break

    if survivor is None:
        # Both operands matched neutral — expression is neutral op neutral
        # e.g. 0 + 0: collapse to zero
        survivor = graph_neutral

    # Rewire: any node pointing to graph_op now points to survivor
    incoming = graph.edges_to(graph_op)
    for e in incoming:
        graph.add_edge(e.source, survivor, e.edge_type)
        graph.remove_edge(e)

    # Remove operator node (edges attached to it are cleaned up by remove_node)
    graph.remove_node(graph_op)


def _zero_product_rewrite(
    graph: PerspectiveGraph,
    result: MatchResult,
    pattern_op: Node,
    pattern_zero: Node
) -> None:
    """
    Rewrite for x * 0 or 0 * x -> 0.
    Replaces the multiplication subtree with a fresh zero node.
    """
    graph_op = result.node_map[pattern_op]

    # Build a new zero node to replace the whole expression
    zero = build_number(graph, 0)

    # Rewire incoming edges
    incoming = graph.edges_to(graph_op)
    for e in incoming:
        graph.add_edge(e.source, zero, e.edge_type)
        graph.remove_edge(e)

    graph.remove_node(graph_op)


# --- Register seed rules ---

_p, _op, _neutral = _make_add_zero_pattern()
register(OperationDefinition(
    name='add_zero_collapse',
    pattern=_p,
    rewrite=lambda g, r: _neutral_element_rewrite(g, r, _op, _neutral)
))

_p, _op, _neutral = _make_mul_one_pattern()
register(OperationDefinition(
    name='mul_one_collapse',
    pattern=_p,
    rewrite=lambda g, r: _neutral_element_rewrite(g, r, _op, _neutral)
))

_p, _op, _neutral = _make_sub_zero_pattern()
register(OperationDefinition(
    name='sub_zero_collapse',
    pattern=_p,
    rewrite=lambda g, r: _neutral_element_rewrite(g, r, _op, _neutral)
))

_p, _op, _neutral = _make_div_one_pattern()
register(OperationDefinition(
    name='div_one_collapse',
    pattern=_p,
    rewrite=lambda g, r: _neutral_element_rewrite(g, r, _op, _neutral)
))

_p, _op, _zero = _make_mul_zero_pattern()
register(OperationDefinition(
    name='mul_zero_collapse',
    pattern=_p,
    rewrite=lambda g, r: _zero_product_rewrite(g, r, _op, _zero)
))