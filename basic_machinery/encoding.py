from __future__ import annotations
from basic_machinery.graph import PerspectiveGraph, Node, EdgeType
from basic_machinery.operations import OperationDefinition, register


# ---------------------------------------------------------------------------
# Tag builders
# ---------------------------------------------------------------------------

def _tag_zero(graph: PerspectiveGraph, node: Node) -> None:
    """Zero: empty node, no tag edges."""
    pass


def _tag_one(graph: PerspectiveGraph, node: Node) -> None:
    """One: single self-loop."""
    graph.add_edge(node, node, EdgeType.STRUCTURAL)


def _tag_parameter(graph: PerspectiveGraph, node: Node) -> None:
    """Parameter: bidirectional edge to a dedicated companion node."""
    companion = graph.add_node()
    graph.add_edge(node, companion, EdgeType.STRUCTURAL)
    graph.add_edge(companion, node, EdgeType.STRUCTURAL)


def _tag_cycle(graph: PerspectiveGraph, node: Node, size: int) -> None:
    """
    Unfinished operator/equality tag.
    Directed cycle of `size` nodes attached to node.
    cycle[0] gets a left anchor node — dead-end structural edge that
    marks operand asymmetry and provides a consistent GA grammar entry point.

    node -> cycle[0] -> cycle[1] -> ... -> cycle[size-1] -> cycle[0]
    cycle[0] -> anchor
    """
    cycle_nodes = [graph.add_node() for _ in range(size)]
    for i in range(size):
        graph.add_edge(cycle_nodes[i], cycle_nodes[(i + 1) % size], EdgeType.STRUCTURAL)
    graph.add_edge(node, cycle_nodes[0], EdgeType.STRUCTURAL)
    anchor = graph.add_node()
    graph.add_edge(cycle_nodes[0], anchor, EdgeType.STRUCTURAL)


def _tag_cycle_plus(graph: PerspectiveGraph, node: Node, size: int) -> None:
    """
    Finished operator/equality tag.
    Same as _tag_cycle but cycle[size-1] also has a tail node.
    Tail presence = finished state. Anchor off cycle[0] = left marker.

    node -> cycle[0] -> ... -> cycle[size-1] -> cycle[0]
                               cycle[size-1] -> tail
    cycle[0] -> anchor
    """
    cycle_nodes = [graph.add_node() for _ in range(size)]
    tail = graph.add_node()
    for i in range(size - 1):
        graph.add_edge(cycle_nodes[i], cycle_nodes[i + 1], EdgeType.STRUCTURAL)
    graph.add_edge(cycle_nodes[-1], cycle_nodes[0], EdgeType.STRUCTURAL)
    graph.add_edge(cycle_nodes[-1], tail, EdgeType.STRUCTURAL)
    graph.add_edge(node, cycle_nodes[0], EdgeType.STRUCTURAL)
    anchor = graph.add_node()
    graph.add_edge(cycle_nodes[0], anchor, EdgeType.STRUCTURAL)


# ---------------------------------------------------------------------------
# Operator and equality node builders
# ---------------------------------------------------------------------------

# Unique cycle size per operator — no overloading, no ambiguity.
# Tail presence (via _tag_cycle_plus) encodes finished state uniformly.
# Sizes 1 and 2 are reserved: 1-cycle = bit value 1, 2-cycle = carry marker.
_OPERATOR_TAGS = {
    '+': 3,
    '-': 4,
    '*': 5,
    '/': 6,
}

_EQUALITY_SIZE = 7


def build_operator(graph: PerspectiveGraph, op: str, finished: bool = False) -> Node:
    """
    Build an operator node with its identifying cycle tag.
    finished=False (default): unfinished, at least one operand contains a parameter.
    finished=True: both operands are concrete numbers, arithmetic rules may fire.
    Returns the operator node.
    """
    if op not in _OPERATOR_TAGS:
        raise ValueError(f"Unknown operator '{op}'. Expected one of {list(_OPERATOR_TAGS)}")
    node = graph.add_node()
    size = _OPERATOR_TAGS[op]
    tag_fn = _tag_cycle_plus if finished else _tag_cycle
    tag_fn(graph, node, size)
    return node


def build_equality(graph: PerspectiveGraph, finished: bool = False) -> Node:
    """
    Build an equality node.
    Unfinished (default): open equation, at least one parameter side.
    Finished: both sides are concrete values — terminal state, no rules fire.
    """
    node = graph.add_node()
    tag_fn = _tag_cycle_plus if finished else _tag_cycle
    tag_fn(graph, node, _EQUALITY_SIZE)
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
        right = _build_bit_tree(graph, bits[-1])   # current LSB
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

    NOTE: order-dependent on insertion order from a set — fragile under
    concurrent rule application. Revisit if multiple rules fire simultaneously.
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
# Seed rule helpers — pattern and transition graph builders
# ---------------------------------------------------------------------------

def _make_neutral_collapse_rule(
    op: str,
    neutral_value: int,
    name: str,
) -> OperationDefinition:
    """
    Build a neutral element collapse rule for the given operator and neutral value.

    Pattern:
      op_node -OPER-> neutral_node   (neutral operand)
      op_node -OPER-> survivor_node  (surviving operand — unconstrained)

    graph2s (strip OPERATIONAL, output STRUCTURAL):
      Input nodes: op_node, neutral_node, survivor_node
      No structural edges added.
      op_node and neutral_node have no outgoing strip-type edges in the
      transition — they are removed in step 4b.
      survivor_node survives. External OPERATIONAL edge from parent to
      op_node is reattached to survivor_node by step 6.

    graph2o: empty — no new operational edges needed.
    """
    # --- Pattern ---
    p = PerspectiveGraph()
    op_node = build_operator(p, op, finished=False)
    neutral_node = build_number(p, neutral_value)
    survivor_node = p.add_node()  # unconstrained — matches any operand root
    p.add_edge(op_node, neutral_node, EdgeType.OPERATIONAL)
    p.add_edge(op_node, survivor_node, EdgeType.OPERATIONAL)

    # --- graph2s ---
    # survivor_node is the only node that survives into the output.
    # It has no outgoing OPERATIONAL edges in the transition, so it is
    # treated as an input node by _apply_pass and mapped to its graph counterpart.
    # op_node and neutral_node are absent from the transition — removed in step 4b.
    g2s = PerspectiveGraph()
    g2s.add_node()  # survivor — no edges, signals preservation

    # --- graph2o ---
    g2o = PerspectiveGraph()

    return OperationDefinition(
        name=name,
        pattern=p,
        graph2s=g2s,
        graph2o=g2o,
    )


def _make_zero_product_rule() -> OperationDefinition:
    """
    Build the x * 0 -> 0 collapse rule.

    Pattern:
      op_node -OPER-> zero_node
      op_node -OPER-> other_node  (the non-zero operand, unconstrained)

    Both operands and the op node are removed. A fresh zero node replaces
    the entire expression. graph2s produces the new zero node's structural
    identity (empty — no structural edges). graph2o is empty.
    """
    # --- Pattern ---
    p = PerspectiveGraph()
    op_node = build_operator(p, '*', finished=False)
    zero_node = build_number(p, 0)
    other_node = p.add_node()
    p.add_edge(op_node, zero_node, EdgeType.OPERATIONAL)
    p.add_edge(op_node, other_node, EdgeType.OPERATIONAL)

    # --- graph2s ---
    # New zero node: empty node, no structural edges.
    # op_node, zero_node, other_node all absent from transition — removed.
    # The new zero node is created fresh by _apply_pass (not in input_match).
    # External OPERATIONAL edge reattaches to it via step 6.
    g2s = PerspectiveGraph()
    g2s.add_node()  # fresh zero node — empty, no edges

    # --- graph2o ---
    g2o = PerspectiveGraph()

    return OperationDefinition(
        name='mul_zero_collapse',
        pattern=p,
        graph2s=g2s,
        graph2o=g2o,
    )


# ---------------------------------------------------------------------------
# Register seed rules
# ---------------------------------------------------------------------------

register(_make_neutral_collapse_rule('+', 0, 'add_zero_collapse'))
register(_make_neutral_collapse_rule('*', 1, 'mul_one_collapse'))
register(_make_neutral_collapse_rule('-', 0, 'sub_zero_collapse'))
register(_make_neutral_collapse_rule('/', 1, 'div_one_collapse'))
register(_make_zero_product_rule())
