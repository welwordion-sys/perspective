from __future__ import annotations
from dataclasses import dataclass
from basic_machinery.graph import PerspectiveGraph, Node, EdgeType
from basic_machinery.operations import OperationDefinition, register


# ---------------------------------------------------------------------------
# Tag handle dataclass
# ---------------------------------------------------------------------------

@dataclass
class OpTag:
    """
    Handles for all internal nodes of an operator/equality tag.
    Returned by build_operator and build_equality so transition graph
    builders can wire explicit OPERATIONAL input→output pairs for each
    tag node.

    tail is None for finished operators (no tail node exists).
    tail is set for unfinished operators (tail = result attachment point).
    """
    cycle_nodes: list[Node]
    anchor: Node
    tail: Node | None


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


def _tag_cycle(graph: PerspectiveGraph, size: int) -> OpTag:
    """
    Finished operator/equality tag (spine/handle migration: operator_port_topology).

    The operator IS the anchored directed cycle. There is NO separate op node.
    HANDLE = cycle[last] (the node a parent attaches its operand pointer to).
    Operand ports are cycle[0] (left, anchored) and cycle[1] (right), wired by
    connect_operands. anchor is a dead-end landmark off cycle[0] marking left.

    cycle[0] -> cycle[1] -> ... -> cycle[size-1] -> cycle[0]   (directed ring)
    cycle[0] -> anchor                                         (left landmark)
    """
    cycle_nodes = [graph.add_node() for _ in range(size)]
    for i in range(size):
        graph.add_edge(cycle_nodes[i], cycle_nodes[(i + 1) % size], EdgeType.STRUCTURAL)
    anchor = graph.add_node()
    graph.add_edge(cycle_nodes[0], anchor, EdgeType.STRUCTURAL)
    return OpTag(cycle_nodes=cycle_nodes, anchor=anchor, tail=None)


def _tag_cycle_plus(graph: PerspectiveGraph, size: int) -> OpTag:
    """
    Unfinished operator/equality tag. Same as _tag_cycle but cycle[last] also
    carries a tail node. Tail presence = unfinished; tail = result attachment
    point. No separate op node; HANDLE = cycle[last].

    cycle[0] -> ... -> cycle[size-1] -> cycle[0]   (directed ring)
                       cycle[size-1] -> tail       (result attach / unfinished mark)
    cycle[0] -> anchor                             (left landmark)
    """
    cycle_nodes = [graph.add_node() for _ in range(size)]
    tail = graph.add_node()
    for i in range(size - 1):
        graph.add_edge(cycle_nodes[i], cycle_nodes[i + 1], EdgeType.STRUCTURAL)
    graph.add_edge(cycle_nodes[-1], cycle_nodes[0], EdgeType.STRUCTURAL)
    graph.add_edge(cycle_nodes[-1], tail, EdgeType.STRUCTURAL)
    anchor = graph.add_node()
    graph.add_edge(cycle_nodes[0], anchor, EdgeType.STRUCTURAL)
    return OpTag(cycle_nodes=cycle_nodes, anchor=anchor, tail=tail)


# ---------------------------------------------------------------------------
# Operator and equality node builders
# ---------------------------------------------------------------------------

# Unique cycle size per operator — no overloading, no ambiguity.
# Tail presence (via _tag_cycle_plus) encodes unfinished state uniformly.
# Sizes 1 and 2 are reserved: 1-cycle = bit value 1, 2-cycle = carry marker.
_OPERATOR_TAGS = {
    '+': 3,
    '-': 4,
    '*': 5,
    '/': 6,
}

_EQUALITY_SIZE = 7


def build_operator(graph: PerspectiveGraph, op: str, finished: bool = False) -> tuple[Node, OpTag]:
    """
    Build an operator as an anchored directed cycle (no separate op node).
    Returns (handle, tag) where handle == tag.cycle_nodes[-1] — the node a
    parent attaches its operand pointer to (parent-in crossing lands on
    cycle[last], per operator_port_topology). Operand ports are cycle[0]/cycle[1],
    wired by connect_operands.
    finished=False: unfinished tag (tail present, result attachment available).
    finished=True: finished tag (no tail).
    """
    if op not in _OPERATOR_TAGS:
        raise ValueError(f"Unknown operator '{op}'. Expected one of {list(_OPERATOR_TAGS)}")
    size = _OPERATOR_TAGS[op]
    tag_fn = _tag_cycle if finished else _tag_cycle_plus  # finished=True -> no tail
    tag = tag_fn(graph, size)
    return tag.cycle_nodes[-1], tag


def build_equality(graph: PerspectiveGraph, finished: bool = False) -> tuple[Node, OpTag]:
    """
    Build an equality as an anchored directed cycle (no separate node).
    Returns (handle, tag) where handle == tag.cycle_nodes[-1].
    """
    tag_fn = _tag_cycle if finished else _tag_cycle_plus
    tag = tag_fn(graph, _EQUALITY_SIZE)
    return tag.cycle_nodes[-1], tag


# ---------------------------------------------------------------------------
# Number encoding
# ---------------------------------------------------------------------------

def build_number(graph: PerspectiveGraph, value: int) -> tuple[Node, Node]:
    """
    Encode a non-negative integer as a SPINE (supersedes the flat bit-chain and
    the older bit-tree; see KB spine_encoding).

    Per bit, LSB->MSB: a SPINE node and a BIT node.
      spine_i -OP-> bit_i          (operational bit pointer; PLAIN edge, raw graph)
      bit_i self-loop STRUCTURAL    iff that bit is 1   (value lives on the bit node)
      spine_i -S-> spine_{i+1}      (structural chain, LSB -> MSB)

    A parent/operator attaches its operand pointer at the LSB spine.
    Returns (handle, lsb) == (lsb_spine, lsb_spine): the LSB spine is both the
    attachment handle and the operational read head. The MSB spine is the far
    end (walk structural successors). value 0 is a single spine whose bit is 0.
    Decode: from lsb spine read its bit (operational neighbour), step to next
    spine (structural), repeat.
    """
    if value < 0:
        raise ValueError("build_number does not handle negative integers.")
    bits = bin(value)[2:][::-1]   # LSB first
    spine: list[Node] = []
    for b in bits:
        s = graph.add_node()
        bit = graph.add_node()
        graph.add_edge(s, bit, EdgeType.OPERATIONAL)        # spine -OP-> bit
        if b == '1':
            graph.add_edge(bit, bit, EdgeType.STRUCTURAL)   # bit value 1
        spine.append(s)
    for i in range(len(spine) - 1):
        graph.add_edge(spine[i], spine[i + 1], EdgeType.STRUCTURAL)  # chain LSB->MSB
    lsb_spine = spine[0]
    return lsb_spine, lsb_spine


# ---------------------------------------------------------------------------
# Parameter encoding
# ---------------------------------------------------------------------------

def build_parameter(graph: PerspectiveGraph) -> tuple[Node, Node]:
    """
    Encode a symbolic parameter (x, y, ...).
    Shape: bidirectional edge to a dedicated companion node.
    All parameters are structurally identical — identity from position
    in the expression tree, not from the node itself.
    Returns (root, lsb) — same node for both since parameters have no bit tree.
    """
    node = graph.add_node()
    _tag_parameter(graph, node)
    return node, node


def build_placeholder(graph: PerspectiveGraph) -> Node:
    """
    External boundary placeholder node.
    Encodes 'this node has a connection outside the matched subgraph.'
    Signature: structural self-loop + operational self-loop.
    Distinct from all other node types in the system:
      - bit 0: no edges
      - bit 1: structural self-loop only
      - tombstone: operational self-loop only
      - placeholder: both self-loops
    Used in transition input subgraphs to mark boundary nodes that have
    external connections in the real graph. Invisible to graph rewriting —
    only used during step 3 matching in _apply_pass.
    """
    node = graph.add_node()
    graph.add_edge(node, node, EdgeType.STRUCTURAL)
    graph.add_edge(node, node, EdgeType.OPERATIONAL)
    return node

# ---------------------------------------------------------------------------
# Expression assembly
# ---------------------------------------------------------------------------

def connect_operands(
    graph: PerspectiveGraph,
    tag: OpTag,
    left_lsb: Node,
    right_lsb: Node,
) -> None:
    """
    Wire an operator's two operand ports to its operands' LSBs (operational).
    Ports are cycle[0] (left, anchored) and cycle[1] (right) — NOT the handle
    (operator_port_topology). The handle (cycle[last]) is the parent-facing
    attachment, kept distinct from the operand ports. Position edges start at
    the operand LSB and walk toward MSB during reduction.
    """
    graph.add_edge(tag.cycle_nodes[0], left_lsb, EdgeType.OPERATIONAL)
    graph.add_edge(tag.cycle_nodes[1], right_lsb, EdgeType.OPERATIONAL)


def connect_equality(
    graph: PerspectiveGraph,
    tag: OpTag,
    left_handle: Node,
    right_handle: Node,
) -> None:
    """
    Wire an equality's two ports to the handles (roots) of its left/right
    expression subtrees (operational). Ports are cycle[0]/cycle[1]; the equality
    reads each side's result-bearing handle, not a bit LSB.
    """
    graph.add_edge(tag.cycle_nodes[0], left_handle, EdgeType.OPERATIONAL)
    graph.add_edge(tag.cycle_nodes[1], right_handle, EdgeType.OPERATIONAL)


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
    (root, _), pos = _parse_equality(graph, tokens, 0)
    if pos != len(tokens):
        raise ValueError(f"Unexpected token at position {pos}: '{tokens[pos]}'")
    return root


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
) -> tuple[tuple[Node, Node], int]:
    left, pos = _parse_additive(graph, tokens, pos)
    if pos < len(tokens) and tokens[pos] == '=':
        pos += 1
        right, pos = _parse_additive(graph, tokens, pos)
        eq_handle, eq_tag = build_equality(graph, finished=False)
        connect_equality(graph, eq_tag, left[0], right[0])
        return (eq_handle, eq_handle), pos
    return left, pos


def _parse_additive(
    graph: PerspectiveGraph, tokens: list[str], pos: int
) -> tuple[Node, int]:
    left, pos = _parse_multiplicative(graph, tokens, pos)
    while pos < len(tokens) and tokens[pos] in ('+', '-'):
        op = tokens[pos]
        pos += 1
        right, pos = _parse_multiplicative(graph, tokens, pos)
        op_handle, op_tag = build_operator(graph, op)
        # left/right are (handle, lsb); operands attach by LSB at cycle[0]/cycle[1]
        connect_operands(graph, op_tag, left[1], right[1])
        left = op_handle, op_handle  # handle (cycle[last]) is this op's root and parent-attach
    return left, pos


def _parse_multiplicative(
    graph: PerspectiveGraph, tokens: list[str], pos: int
) -> tuple[Node, int]:
    left, pos = _parse_primary(graph, tokens, pos)
    while pos < len(tokens) and tokens[pos] in ('*', '/'):
        op = tokens[pos]
        pos += 1
        right, pos = _parse_primary(graph, tokens, pos)
        op_handle, op_tag = build_operator(graph, op)
        connect_operands(graph, op_tag, left[1], right[1])
        left = op_handle, op_handle
    return left, pos


def _parse_primary(
    graph: PerspectiveGraph, tokens: list[str], pos: int
) -> tuple[tuple[Node, Node], int]:
    if pos >= len(tokens):
        raise ValueError("Unexpected end of expression.")
    token = tokens[pos]
    if token == '(':
        node, pos = _parse_equality(graph, tokens, pos + 1)
        if pos >= len(tokens) or tokens[pos] != ')':
            raise ValueError("Expected closing parenthesis.")
        return node, pos + 1
    if token == 'x':
        root, lsb = build_parameter(graph)
        return (root, lsb), pos + 1
    if token.isdigit() or (len(token) > 1 and token.isdigit()):
        root, lsb = build_number(graph, int(token))
        return (root, lsb), pos + 1
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
    op_node, _ = build_operator(p, op, finished=False)
    _, neutral_lsb = build_number(p, neutral_value)
    survivor_node = p.add_node()
    p.add_edge(op_node, neutral_lsb, EdgeType.OPERATIONAL)
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
        graph2=g2s,
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
    op_node, _ = build_operator(p, '*', finished=False)
    _, zero_lsb = build_number(p, 0)
    other_node = p.add_node()
    p.add_edge(op_node, zero_lsb, EdgeType.OPERATIONAL)
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
        graph2=g2s,
    )


# ---------------------------------------------------------------------------
# Register seed rules
# ---------------------------------------------------------------------------

register(_make_neutral_collapse_rule('+', 0, 'add_zero_collapse'))
register(_make_neutral_collapse_rule('*', 1, 'mul_one_collapse'))
register(_make_neutral_collapse_rule('-', 0, 'sub_zero_collapse'))
register(_make_neutral_collapse_rule('/', 1, 'div_one_collapse'))
register(_make_zero_product_rule())
