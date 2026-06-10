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
    Finished operator/equality tag. The operator IS this anchored cycle —
    there is no separate op node (eliminated per operator_port_topology).

    Directed structural cycle of `size` nodes. No tail.
    cycle[0] is the operator handle AND the left-operand port; it carries a
    dead-end structural edge to an anchor node. Distance-from-anchor is what
    orders the operand ports: cycle[0] (anchored) = left, cycle[1] = right.

    Ports (wired later by connect_operands / parent attachment):
      left  -> cycle[0]   (anchored)
      right -> cycle[1]
      parent-in -> cycle[last]
      result -> off the tail (finished tag has no tail; see _tag_cycle_plus)

    cycle[0] -> cycle[1] -> ... -> cycle[size-1] -> cycle[0]
    cycle[0] -> anchor
    """
    cycle_nodes = [graph.add_node() for _ in range(size)]
    for i in range(size):
        graph.add_edge(cycle_nodes[i], cycle_nodes[(i + 1) % size], EdgeType.STRUCTURAL)
    anchor = graph.add_node()
    graph.add_edge(cycle_nodes[0], anchor, EdgeType.STRUCTURAL)
    return OpTag(cycle_nodes=cycle_nodes, anchor=anchor, tail=None)


def _tag_cycle_plus(graph: PerspectiveGraph, size: int) -> OpTag:
    """
    Unfinished operator/equality tag. The operator IS this anchored cycle —
    no separate op node (operator_port_topology).

    Same as _tag_cycle but cycle[size-1] also has a tail node.
    Tail presence = unfinished state. Tail = result buffer attachment point
    (add_init repurposes it as the result buffer; see add_init_result_construction).
    Anchor off cycle[0] = left marker / handle.

    cycle[0] -> ... -> cycle[size-1] -> cycle[0]
                       cycle[size-1] -> tail
    cycle[0] -> anchor
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
    Build an operator as an anchored directed cycle (operator_port_topology).
    Returns (handle, tag) where handle IS tag.cycle_nodes[-1] (cycle[last]) — the
    node a PARENT attaches its operand pointer to (parent-in crossing). The
    operand ports are separate: left -> cycle[0] (anchored), right -> cycle[1].
    There is no separate op node.

    finished=False: unfinished tag (tail present, result buffer point available).
    finished=True: finished tag (no tail, stuck/halted form).
    """
    if op not in _OPERATOR_TAGS:
        raise ValueError(f"Unknown operator '{op}'. Expected one of {list(_OPERATOR_TAGS)}")
    size = _OPERATOR_TAGS[op]
    tag_fn = _tag_cycle if finished else _tag_cycle_plus
    tag = tag_fn(graph, size)
    return tag.cycle_nodes[-1], tag


def build_equality(graph: PerspectiveGraph, finished: bool = False) -> tuple[Node, OpTag]:
    """
    Build an equality node as an anchored directed cycle (size 7).
    Returns (handle, tag) where handle IS tag.cycle_nodes[-1] (cycle[last]).
    The = is the top node (testcases_always_equation), so nothing points into
    its cycle[last]; the handle is still the canonical root reference.
    """
    tag_fn = _tag_cycle if finished else _tag_cycle_plus
    tag = tag_fn(graph, _EQUALITY_SIZE)
    return tag.cycle_nodes[-1], tag


# ---------------------------------------------------------------------------
# Number encoding
# ---------------------------------------------------------------------------

def build_number(graph: PerspectiveGraph, value: int) -> tuple[Node, Node]:
    """
    Encode a non-negative integer as an open-length BIT CHAIN.

    Structure (operand_is_bit_chain): one node per bit, linked LSB -> MSB by
    structural edges:  lsb -S-> b1 -S-> ... -S-> msb.
    Bit value: structural self-loop = 1, bare node = 0 (unchanged convention).
    The operator attaches its operational pointer at the LSB; advancing one bit
    toward the MSB is a single structural hop along the chain.

    Returns (root, lsb) where root == lsb: the LSB is both the operator/nesting
    attachment handle and the head of the chain. The MSB is the chain's far end
    (reached by walking structural edges); result chains attach at the MSB for
    matching, operands at the LSB.

    Replaces the former binary-tree encoding (spine of internal nodes with bit
    leaves on the side), which carried the same bit order but forced a
    spine<->leaf hop per bit and gave operands a different shape from results.
    No capability was lost in the switch (no sub-range-as-node addressing is
    used anywhere); the chain makes operand and result the same shape and makes
    the LSB->MSB walk one structural edge per bit.
    """
    if value < 0:
        raise ValueError("build_number does not handle negative integers.")
    bits = bin(value)[2:]                  # MSB first
    lsb_to_msb = bits[::-1]                 # index 0 = LSB
    nodes = [graph.add_node() for _ in lsb_to_msb]
    for i, b in enumerate(lsb_to_msb):
        if b == '1':
            graph.add_edge(nodes[i], nodes[i], EdgeType.STRUCTURAL)  # bit value 1
        if i + 1 < len(nodes):
            graph.add_edge(nodes[i], nodes[i + 1], EdgeType.STRUCTURAL)  # LSB -> MSB chain
    lsb = nodes[0]
    return lsb, lsb  # root == lsb: LSB is the attachment handle (head of chain)


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
    left_root: Node,
    left_lsb: Node,
    right_root: Node,
    right_lsb: Node,
) -> None:
    """
    Connect an operator (anchored cycle) to the LSBs of its two operand
    subtrees via operational edges, using DISTINCT ports so left/right are
    positionally discriminable (operator_port_topology, operand_order_gap):
      left  operand LSB <- cycle[0]  (anchored port)
      right operand LSB <- cycle[1]
    Position edges start at LSB and walk toward MSB during reduction.
    """
    graph.add_edge(tag.cycle_nodes[0], left_lsb,  EdgeType.OPERATIONAL)
    graph.add_edge(tag.cycle_nodes[1], right_lsb, EdgeType.OPERATIONAL)


def connect_equality(
    graph: PerspectiveGraph,
    tag: OpTag,
    left_root: Node,
    right_root: Node,
) -> None:
    """
    Connect an equality (anchored cycle, size 7) to the roots of its left and
    right expression subtrees via operational edges, distinct ports:
      left  root <- cycle[0]  (anchored)
      right root <- cycle[1]
    """
    graph.add_edge(tag.cycle_nodes[0], left_root,  EdgeType.OPERATIONAL)
    graph.add_edge(tag.cycle_nodes[1], right_root, EdgeType.OPERATIONAL)


def get_operands(graph: PerspectiveGraph, tag: OpTag) -> tuple[Node, Node]:
    """
    Return the (left, right) operand targets of an operator/equality.
    Left is the operational target off cycle[0] (anchored port), right off
    cycle[1]. Positional — no longer dependent on set insertion order, which
    was the operand-order discrimination defect (operand_order_gap_root_cause).
    Raises if either port does not carry exactly one operational edge.
    """
    left_edges  = graph.edges_from(tag.cycle_nodes[0], EdgeType.OPERATIONAL)
    right_edges = graph.edges_from(tag.cycle_nodes[1], EdgeType.OPERATIONAL)
    left_edges  = [e for e in left_edges  if e.target != e.source]
    right_edges = [e for e in right_edges if e.target != e.source]
    if len(left_edges) != 1 or len(right_edges) != 1:
        raise ValueError(
            f"Expected one operational edge on each operand port; "
            f"got left={len(left_edges)}, right={len(right_edges)}."
        )
    return left_edges[0].target, right_edges[0].target


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
        handle, tag = build_operator(graph, op)
        # left and right are (root, lsb) tuples from _parse_primary
        connect_operands(graph, tag, left[0], left[1], right[0], right[1])
        # The operator's handle (cycle[0]) is its root; a parent attaches its
        # operand pointer here. lsb placeholder = handle (operators have no bit tree).
        left = handle, handle
    return left, pos


def _parse_multiplicative(
    graph: PerspectiveGraph, tokens: list[str], pos: int
) -> tuple[Node, int]:
    left, pos = _parse_primary(graph, tokens, pos)
    while pos < len(tokens) and tokens[pos] in ('*', '/'):
        op = tokens[pos]
        pos += 1
        right, pos = _parse_primary(graph, tokens, pos)
        handle, tag = build_operator(graph, op)
        connect_operands(graph, tag, left[0], left[1], right[0], right[1])
        left = handle, handle
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
    # Neutral element is the RIGHT operand (x - 0, x / 1, x + 0, x * 1).
    # Survivor is the LEFT operand. The new port topology makes this
    # distinction expressible; the old symmetric wiring could not, and would
    # wrongly match e.g. 0 - x. survivor -> cycle[0], neutral -> cycle[1].
    p = PerspectiveGraph()
    op_handle, op_tag = build_operator(p, op, finished=False)
    _, neutral_lsb = build_number(p, neutral_value)
    survivor_node = p.add_node()
    connect_operands(p, op_tag, survivor_node, survivor_node, neutral_lsb, neutral_lsb)

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
    # x * 0: commutative, so operand order is harmless, but wire through ports
    # for consistency. other -> cycle[0] (left), zero -> cycle[1] (right).
    p = PerspectiveGraph()
    op_handle, op_tag = build_operator(p, '*', finished=False)
    _, zero_lsb = build_number(p, 0)
    other_node = p.add_node()
    connect_operands(p, op_tag, other_node, other_node, zero_lsb, zero_lsb)

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
