"""
tests/test_arithmetic.py

Tests for arithmetic.py rules against the triple graph schema (operations.py).
Run from project root: pytest tests/test_arithmetic.py -v

Coverage priority:
  1. add_init_00 — validates full apply() pipeline end-to-end
  2. add_init_11 — carry-out case in init
  3. bit_add_01_c0 — position advance + result retagging
  4. bit_add_11_c1 — carry propagation
  5. drain_left_1_c0 — active side drains, exhausted side stays
  6. add_finalise_00_c0 — both MSBs done, no carry
  7. add_finalise_11_c1 — carry overflow to extra MSB node
  8. tombstone_gc — self-loop tombstone propagates to child
  9. Full 1+1=2 end-to-end — applies rules in sequence, checks result tree
 10. Full 3+1=4 end-to-end — unequal lengths, exercises drain path
"""

from __future__ import annotations
import pytest
from basic_machinery.graph import PerspectiveGraph, Node, EdgeType
from basic_machinery.encoding import build_number, build_operator, connect_operands
from basic_machinery.operations import apply, lookup, match
import basic_machinery.arithmetic  # noqa: F401 — side effect: registers all rules


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def op_edges(g: PerspectiveGraph, node: Node) -> list:
    return g.edges_from(node, EdgeType.OPERATIONAL)

def struct_edges(g: PerspectiveGraph, node: Node) -> list:
    return g.edges_from(node, EdgeType.STRUCTURAL)

def is_zero(g: PerspectiveGraph, node: Node) -> bool:
    return len(struct_edges(g, node)) == 0

def is_one(g: PerspectiveGraph, node: Node) -> bool:
    edges = struct_edges(g, node)
    return len(edges) == 1 and edges[0].target == node

def has_tombstone(g: PerspectiveGraph, node: Node) -> bool:
    """Operational self-loop on node."""
    return any(
        e.target == node
        for e in g.edges_from(node, EdgeType.OPERATIONAL)
    )

def has_carry(g: PerspectiveGraph, result_node: Node) -> bool:
    """
    Carry = result_node -OPER-> cycle_a -STRUCT-> cycle_b -STRUCT-> cycle_a.
    """
    for e in g.edges_from(result_node, EdgeType.OPERATIONAL):
        ca = e.target
        if ca == result_node:
            continue
        out = g.edges_from(ca, EdgeType.STRUCTURAL)
        if len(out) == 1:
            cb = out[0].target
            if cb != ca:
                back = g.edges_from(cb, EdgeType.STRUCTURAL)
                if len(back) == 1 and back[0].target == ca:
                    return True
    return False

def find_result_node(g: PerspectiveGraph, op_node: Node, nodes_before: set) -> Node | None:
    """
    Result node = new node (not in nodes_before) that op_node has an operational edge to.
    """
    new_nodes = set(g.nodes) - nodes_before
    for e in g.edges_from(op_node, EdgeType.OPERATIONAL):
        if e.target in new_nodes:
            return e.target
    return None

def read_binary_tree(g: PerspectiveGraph, root: Node) -> int:
    """
    Read a binary number from a tree rooted at root.
    MSB at root, LSB at deepest leaf.
    """
    def collect_bits(node: Node) -> list[int]:
        bit = 1 if is_one(g, node) else 0
        children = [
            e.target for e in g.edges_from(node, EdgeType.STRUCTURAL)
            if e.target != node
        ]
        if not children:
            return [bit]
        return [bit] + collect_bits(children[0])

    bits = collect_bits(root)
    value = 0
    for b in bits:
        value = value * 2 + b
    return value

def build_addition_graph(left_val: int, right_val: int) -> tuple[PerspectiveGraph, Node]:
    """
    Build a graph encoding (left_val + right_val).
    Returns (graph, op_node).
    """
    g = PerspectiveGraph()
    left_root, left_lsb = build_number(g, left_val)
    right_root, right_lsb = build_number(g, right_val)
    op_node, _ = build_operator(g, '+', finished=False)
    connect_operands(g, op_node, left_root, left_lsb, right_root, right_lsb)
    return g, op_node

def run_until_stable(g: PerspectiveGraph, rule_names: list[str], max_steps: int = 200) -> int:
    """Apply rules in order, cycling until no rule fires. Returns step count."""
    ops = [lookup(name) for name in rule_names]
    for step in range(max_steps):
        fired = False
        for op in ops:
            if apply(g, op):
                fired = True
                break
        if not fired:
            return step
    raise AssertionError(f"Did not stabilise within {max_steps} steps")


# ---------------------------------------------------------------------------
# 1. add_init_00 — 0+0 first bit step, no carry
# ---------------------------------------------------------------------------

class TestAddInit00:
    def setup_method(self):
        self.g, self.op = build_addition_graph(0, 0)
        self.op_def = lookup('add_init_00')
        self.nodes_before = set(self.g.nodes)

    def test_pattern_matches(self):
        result = match(self.op_def.pattern, self.g)
        assert result.success

    def test_apply_returns_true(self):
        assert apply(self.g, self.op_def)

    def test_result_node_created(self):    
        apply(self.g, self.op_def)
        result = find_result_node(self.g, self.op, self.nodes_before)
        assert result is not None, f"No result node found. nodes={list(self.g.nodes)} edges={list(self.g.edges)}"

    def test_result_bit_is_zero(self):
        apply(self.g, self.op_def)
        result = find_result_node(self.g, self.op, self.nodes_before)
        assert result is not None
        assert is_zero(self.g, result), "Result bit should be 0 for 0+0"

    def test_no_carry_produced(self):
        apply(self.g, self.op_def)
        result = find_result_node(self.g, self.op, self.nodes_before)
        assert result is not None
        assert not has_carry(self.g, result), "0+0 should not produce carry"

    def test_position_edges_advanced(self):
        apply(self.g, self.op_def)
        edges = op_edges(self.g, self.op)
        assert len(edges) == 3, f"Expected 3 op edges after add_init_00, got {len(edges)}"


# ---------------------------------------------------------------------------
# 2. add_init_11 — 1+1 first bit step, carry produced
# ---------------------------------------------------------------------------

class TestAddInit11:
    def setup_method(self):
        self.g, self.op = build_addition_graph(1, 1)
        self.op_def = lookup('add_init_11')
        self.nodes_before = set(self.g.nodes)

    def test_apply_returns_true(self):
        assert apply(self.g, self.op_def)

    def test_result_bit_is_zero(self):
        apply(self.g, self.op_def)
        result = find_result_node(self.g, self.op, self.nodes_before)
        assert result is not None
        assert is_zero(self.g, result), "1+1 LSB result should be 0"

    def test_carry_produced(self):
        apply(self.g, self.op_def)
        result = find_result_node(self.g, self.op, self.nodes_before)
        assert result is not None
        assert has_carry(self.g, result), "1+1 should produce carry"


# ---------------------------------------------------------------------------
# 3. bit_add_01_c0 — mid-step: left=0, right=1, no carry in
# ---------------------------------------------------------------------------

class TestBitAdd01C0:
    def setup_method(self):
        self.g, self.op = build_addition_graph(2, 1)
        assert apply(self.g, lookup('add_init_01')), "add_init_01 should fire on 2+1"
        self.nodes_before = set(self.g.nodes)
        self.op_def = lookup('bit_add_01_c0')

    def test_pattern_matches(self):
        result = match(self.op_def.pattern, self.g)
        assert result.success

    def test_apply_returns_true(self):
        assert apply(self.g, self.op_def)

    def test_result_bit_is_one(self):
        apply(self.g, self.op_def)
        result = find_result_node(self.g, self.op, self.nodes_before)
        assert result is not None
        assert is_one(self.g, result), "0+1 should give result bit 1"

    def test_no_carry(self):
        apply(self.g, self.op_def)
        result = find_result_node(self.g, self.op, self.nodes_before)
        assert result is not None
        assert not has_carry(self.g, result)


# ---------------------------------------------------------------------------
# 4. bit_add_11_c1 — mid-step: left=1, right=1, carry in -> carry out
# ---------------------------------------------------------------------------

class TestBitAdd11C1:
    def setup_method(self):
        self.g, self.op = build_addition_graph(3, 3)
        assert apply(self.g, lookup('add_init_11'))
        self.nodes_before = set(self.g.nodes)
        self.op_def = lookup('bit_add_11_c1')

    def test_pattern_matches(self):
        result = match(self.op_def.pattern, self.g)
        assert result.success

    def test_result_bit_is_one(self):
        apply(self.g, self.op_def)
        result = find_result_node(self.g, self.op, self.nodes_before)
        assert result is not None
        assert is_one(self.g, result), "1+1+1 result bit should be 1"

    def test_carry_out(self):
        apply(self.g, self.op_def)
        result = find_result_node(self.g, self.op, self.nodes_before)
        assert result is not None
        assert has_carry(self.g, result), "1+1+1 should carry out"


# ---------------------------------------------------------------------------
# 5. drain_left — active left side drains, right exhausted
# ---------------------------------------------------------------------------

class TestDrainLeft:
    def setup_method(self):
        self.g, self.op = build_addition_graph(2, 0)
        assert apply(self.g, lookup('add_init_00'))
        self.nodes_before = set(self.g.nodes)
        self.op_def = lookup('drain_left_1_c0')

    def test_pattern_matches(self):
        result = match(self.op_def.pattern, self.g)
        assert result.success

    def test_apply_returns_true(self):
        assert apply(self.g, self.op_def)

    def test_result_bit_is_one(self):
        apply(self.g, self.op_def)
        result = find_result_node(self.g, self.op, self.nodes_before)
        assert result is not None
        assert is_one(self.g, result), "Draining 1 with no carry should give bit=1"


# ---------------------------------------------------------------------------
# 6. add_finalise_00_c0 — both MSBs 0, no carry
# ---------------------------------------------------------------------------

class TestAddFinalise00C0:
    def setup_method(self):
        self.g, self.op = build_addition_graph(0, 0)
        assert apply(self.g, lookup('add_init_00'))
        self.nodes_before = set(self.g.nodes)
        self.op_def = lookup('add_finalise_00_c0')

    def test_pattern_matches(self):
        result = match(self.op_def.pattern, self.g)
        assert result.success

    def test_apply_returns_true(self):
        assert apply(self.g, self.op_def)

    def test_op_node_removed(self):
        apply(self.g, self.op_def)
        assert self.op not in self.g.nodes, "Op node should be removed after finalise"

    def test_result_accessible(self):
        # Find result node before finalise — it's a new node from add_init
        init_nodes_before = set()
        result_before = find_result_node(self.g, self.op, init_nodes_before)
        apply(self.g, self.op_def)
        assert result_before in self.g.nodes, "Result node should survive finalise"


# ---------------------------------------------------------------------------
# 7. add_finalise with carry overflow
# ---------------------------------------------------------------------------

class TestAddFinaliseCarryOverflow:
    def setup_method(self):
        self.g, self.op = build_addition_graph(1, 1)
        assert apply(self.g, lookup('add_init_11'))
        self.op_def = lookup('add_finalise_00_c1')

    def test_pattern_matches(self):
        result = match(self.op_def.pattern, self.g)
        assert result.success

    def test_apply_returns_true(self):
        assert apply(self.g, self.op_def)

    def test_extra_msb_created(self):
        apply(self.g, self.op_def)
        # 1+1=10: find a node with value=1 that has a zero child
        found = False
        for node in self.g.nodes:
            children = [
                e.target for e in self.g.edges_from(node, EdgeType.STRUCTURAL)
                if e.target != node
            ]
            if len(children) == 1:
                child = children[0]
                if is_one(self.g, node) and is_zero(self.g, child):
                    found = True
                    break
        assert found, "Expected result tree encoding 10 (binary) = 2"


# ---------------------------------------------------------------------------
# 8. tombstone_gc
# ---------------------------------------------------------------------------

class TestTombstoneGC:
    def setup_method(self):
        self.g = PerspectiveGraph()
        self.parent = self.g.add_node()
        self.child = self.g.add_node()
        self.g.add_edge(self.parent, self.child, EdgeType.STRUCTURAL)
        self.g.add_edge(self.parent, self.parent, EdgeType.OPERATIONAL)
        self.op_def = lookup('tombstone_gc')

    def test_pattern_matches(self):
        result = match(self.op_def.pattern, self.g)
        assert result.success

    def test_apply_returns_true(self):
        assert apply(self.g, self.op_def)

    def test_parent_removed(self):
        apply(self.g, self.op_def)
        assert self.parent not in self.g.nodes

    def test_child_gets_tombstone(self):
        apply(self.g, self.op_def)
        assert has_tombstone(self.g, self.child), "Child should inherit tombstone"

    def test_second_gc_removes_child(self):
        apply(self.g, self.op_def)
        result = match(self.op_def.pattern, self.g)
        if result.success:
            apply(self.g, self.op_def)
        assert self.child not in self.g.nodes


# ---------------------------------------------------------------------------
# 9. End-to-end: 1 + 1 = 2
# ---------------------------------------------------------------------------

class TestEndToEnd1Plus1:
    ADD_RULES = [
        'add_init_11', 'add_init_10', 'add_init_01', 'add_init_00',
        'bit_add_00_c0', 'bit_add_01_c0', 'bit_add_10_c0', 'bit_add_11_c0',
        'bit_add_00_c1', 'bit_add_01_c1', 'bit_add_10_c1', 'bit_add_11_c1',
        'drain_left_0_c0', 'drain_left_1_c0', 'drain_left_0_c1', 'drain_left_1_c1',
        'drain_right_0_c0', 'drain_right_1_c0', 'drain_right_0_c1', 'drain_right_1_c1',
        'add_finalise_00_c0', 'add_finalise_01_c0', 'add_finalise_10_c0', 'add_finalise_11_c0',
        'add_finalise_00_c1', 'add_finalise_01_c1', 'add_finalise_10_c1', 'add_finalise_11_c1',
    ]

    def test_result_is_2(self):
        g, op = build_addition_graph(1, 1)
        run_until_stable(g, self.ADD_RULES)
        found_root = None
        for node in g.nodes:
            if is_one(g, node):
                children = [
                    e.target for e in g.edges_from(node, EdgeType.STRUCTURAL)
                    if e.target != node
                ]
                if len(children) == 1 and is_zero(g, children[0]):
                    found_root = node
                    break
        assert found_root is not None, "No result tree encoding 2 (binary 10) found"
        assert read_binary_tree(g, found_root) == 2


# ---------------------------------------------------------------------------
# 10. End-to-end: 3 + 1 = 4 (exercises drain path)
# ---------------------------------------------------------------------------

class TestEndToEnd3Plus1:
    ADD_RULES = TestEndToEnd1Plus1.ADD_RULES

    def test_result_is_4(self):
        g, op = build_addition_graph(3, 1)
        run_until_stable(g, self.ADD_RULES)
        found_root = None
        for node in g.nodes:
            if is_one(g, node):
                ch1 = [
                    e.target for e in g.edges_from(node, EdgeType.STRUCTURAL)
                    if e.target != node
                ]
                if len(ch1) == 1 and is_zero(g, ch1[0]):
                    ch2 = [
                        e.target for e in g.edges_from(ch1[0], EdgeType.STRUCTURAL)
                        if e.target != ch1[0]
                    ]
                    if len(ch2) == 1 and is_zero(g, ch2[0]):
                        found_root = node
                        break
        assert found_root is not None, "No result tree encoding 4 (binary 100) found"
        assert read_binary_tree(g, found_root) == 4
