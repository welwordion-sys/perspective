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
from basic_machinery.encoding import encode, build_number, build_operator, connect_operands
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

def find_op_node(g: PerspectiveGraph) -> Node:
    """Find the + operator node — the one with a 3-cycle reachable from it."""
    for node in g.nodes:
        edges = struct_edges(g, node)
        if len(edges) == 1:
            nxt = edges[0].target
            if nxt != node:
                # check 3-cycle: node -> nxt -> nxt2 -> node
                nxt_edges = struct_edges(g, nxt)
                if len(nxt_edges) == 1:
                    nxt2 = nxt_edges[0].target
                    nxt2_edges = struct_edges(g, nxt2)
                    if len(nxt2_edges) == 1 and nxt2_edges[0].target == node:
                        return node
    raise AssertionError("No + operator node found in graph")

def get_result_root(g: PerspectiveGraph, op_node: Node) -> Node | None:
    """
    Result root = operational target of op_node that is NOT in either operand tree.
    Operand roots are op_edges[0] and op_edges[1].
    """
    edges = op_edges(g, op_node)
    if len(edges) < 3:
        return None
    operand_roots = {edges[0].target, edges[1].target}

    def in_tree(root: Node, target: Node) -> bool:
        visited: set[Node] = set()
        stack = [root]
        while stack:
            n = stack.pop()
            if n == target:
                return True
            if n in visited:
                continue
            visited.add(n)
            for e in g.edges_from(n, EdgeType.STRUCTURAL):
                stack.append(e.target)
        return False

    for e in edges[2:]:
        if not any(in_tree(r, e.target) for r in operand_roots):
            return e.target
    return None

def read_binary_tree(g: PerspectiveGraph, root: Node) -> int:
    """
    Read a binary number from a tree rooted at root.
    MSB at root, LSB at deepest right leaf.
    Left child = structural child[0], right child = structural child[1] (if exists).
    """
    def collect_bits(node: Node) -> list[int]:
        bit = 1 if is_one(g, node) else 0
        children = [
            e.target for e in g.edges_from(node, EdgeType.STRUCTURAL)
            if e.target != node
        ]
        if not children:
            return [bit]
        right = children[1] if len(children) >= 2 else children[0]
        return [bit] + collect_bits(right)

    bits = collect_bits(root)
    # bits[0] is MSB. Convert: sum(bit * 2^(len-1-i) for i, bit in enumerate(bits))
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
    op_node = build_operator(g, '+', finished=False)
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

    def test_pattern_matches(self):
        result = match(self.op_def.pattern, self.g)
        assert result.success

    def test_apply_returns_true(self):
        assert apply(self.g, self.op_def)

    def test_result_node_created(self):
        apply(self.g, self.op_def)
        result = get_result_root(self.g, self.op)
        assert result is not None, "No result node found after add_init_00"

    def test_result_bit_is_zero(self):
        apply(self.g, self.op_def)
        result = get_result_root(self.g, self.op)
        assert is_zero(self.g, result), "Result bit should be 0 for 0+0"

    def test_no_carry_produced(self):
        apply(self.g, self.op_def)
        result = get_result_root(self.g, self.op)
        assert not has_carry(self.g, result), "0+0 should not produce carry"

    def test_position_edges_advanced(self):
        apply(self.g, self.op_def)
        # After init on single-bit numbers (0), both positions advanced to
        # parent — which for a single-node number means exhausted.
        # op should have 3 operational edges: left_root, right_root, result
        edges = op_edges(self.g, self.op)
        assert len(edges) == 3, f"Expected 3 op edges after add_init_00, got {len(edges)}"


# ---------------------------------------------------------------------------
# 2. add_init_11 — 1+1 first bit step, carry produced
# ---------------------------------------------------------------------------

class TestAddInit11:
    def setup_method(self):
        self.g, self.op = build_addition_graph(1, 1)
        self.op_def = lookup('add_init_11')

    def test_apply_returns_true(self):
        assert apply(self.g, self.op_def)

    def test_result_bit_is_zero(self):
        apply(self.g, self.op_def)
        result = get_result_root(self.g, self.op)
        assert result is not None
        assert is_zero(self.g, result), "1+1 LSB result should be 0"

    def test_carry_produced(self):
        apply(self.g, self.op_def)
        result = get_result_root(self.g, self.op)
        assert has_carry(self.g, result), "1+1 should produce carry"


# ---------------------------------------------------------------------------
# 3. bit_add_01_c0 — mid-step: left=0, right=1, no carry in
# ---------------------------------------------------------------------------

class TestBitAdd01C0:
    def setup_method(self):
        # Build 2+1 = 10+01 in binary. After add_init_10 on LSBs (0+1):
        # result bit = 1, positions advance to next bit.
        # We'll directly construct the mid-state.
        self.g, self.op = build_addition_graph(2, 1)
        # Run add_init to get into mid-reduction state
        assert apply(self.g, lookup('add_init_01')), "add_init_01 should fire on 2+1"
        self.op_def = lookup('bit_add_01_c0')

    def test_pattern_matches(self):
        result = match(self.op_def.pattern, self.g)
        assert result.success

    def test_apply_returns_true(self):
        assert apply(self.g, self.op_def)

    def test_result_bit_is_one(self):
        apply(self.g, self.op_def)
        result = get_result_root(self.g, self.op)
        assert result is not None
        assert is_one(self.g, result), "0+1 should give result bit 1"

    def test_no_carry(self):
        apply(self.g, self.op_def)
        result = get_result_root(self.g, self.op)
        assert not has_carry(self.g, result)


# ---------------------------------------------------------------------------
# 4. bit_add_11_c1 — mid-step: left=1, right=1, carry in → carry out
# ---------------------------------------------------------------------------

class TestBitAdd11C1:
    def setup_method(self):
        # 3+3 = 11+11. After add_init_11: result=0, carry=1, positions at MSB.
        # Next: bit_add_11_c1 fires on MSBs.
        self.g, self.op = build_addition_graph(3, 3)
        assert apply(self.g, lookup('add_init_11'))
        self.op_def = lookup('bit_add_11_c1')

    def test_pattern_matches(self):
        result = match(self.op_def.pattern, self.g)
        assert result.success

    def test_result_bit_is_one(self):
        # 1+1+1 = 3 → bit=1, carry=1
        apply(self.g, self.op_def)
        result = get_result_root(self.g, self.op)
        assert result is not None
        assert is_one(self.g, result), "1+1+1 result bit should be 1"

    def test_carry_out(self):
        apply(self.g, self.op_def)
        result = get_result_root(self.g, self.op)
        assert has_carry(self.g, result), "1+1+1 should carry out"


# ---------------------------------------------------------------------------
# 5. drain_left — active left side drains, right exhausted
# ---------------------------------------------------------------------------

class TestDrainLeft:
    def setup_method(self):
        # 2+0 = 10+0. add_init fires on 0+0 (LSBs). Result=0, no carry.
        # Right is now exhausted (single bit), left still has MSB.
        # drain_left_1_c0 should fire (left MSB=1, no carry).
        self.g, self.op = build_addition_graph(2, 0)
        assert apply(self.g, lookup('add_init_00'))
        self.op_def = lookup('drain_left_1_c0')

    def test_pattern_matches(self):
        result = match(self.op_def.pattern, self.g)
        assert result.success

    def test_apply_returns_true(self):
        assert apply(self.g, self.op_def)

    def test_result_bit_is_one(self):
        apply(self.g, self.op_def)
        result = get_result_root(self.g, self.op)
        assert result is not None
        assert is_one(self.g, result), "Draining 1 with no carry should give bit=1"


# ---------------------------------------------------------------------------
# 6. add_finalise_00_c0 — both MSBs 0, no carry
# ---------------------------------------------------------------------------

class TestAddFinalise00C0:
    def setup_method(self):
        # 0+0: after add_init_00, both positions exhausted, result=0, no carry.
        # add_finalise_00_c0 should fire.
        self.g, self.op = build_addition_graph(0, 0)
        assert apply(self.g, lookup('add_init_00'))
        self.op_def = lookup('add_finalise_00_c0')

    def test_pattern_matches(self):
        result = match(self.op_def.pattern, self.g)
        assert result.success

    def test_apply_returns_true(self):
        assert apply(self.g, self.op_def)

    def test_op_node_removed(self):
        node_before = self.op
        apply(self.g, self.op_def)
        assert node_before not in self.g.nodes, "Op node should be removed after finalise"

    def test_result_accessible(self):
        # After finalise, op node is gone. The result tree root should be
        # reachable from wherever op node's parent was — but for a standalone
        # graph with no parent, we just check the result node still exists.
        result_before = get_result_root(self.g, self.op)
        apply(self.g, self.op_def)
        assert result_before in self.g.nodes, "Result node should survive finalise"


# ---------------------------------------------------------------------------
# 7. add_finalise with carry overflow
# ---------------------------------------------------------------------------

class TestAddFinaliseCarryOverflow:
    def setup_method(self):
        # 1+1: add_init_11 → result=0, carry=1, positions exhausted.
        # add_finalise_00_c1 fires: result bit = 0+0+1=1, carry_out=0.
        # No extra MSB needed here. Use 3+1=100 for overflow:
        # 3=11, 1=01. add_init_11 → result=0, carry. bit_add_10_c1 on MSBs
        # (left=1, right=0, carry=1): total=2, bit=0, carry=1 → add_finalise_00_c1.
        # Actually just test 1+1 directly for the carry-in finalise case.
        self.g, self.op = build_addition_graph(1, 1)
        assert apply(self.g, lookup('add_init_11'))
        self.op_def = lookup('add_finalise_00_c1')

    def test_pattern_matches(self):
        result = match(self.op_def.pattern, self.g)
        assert result.success

    def test_apply_returns_true(self):
        assert apply(self.g, self.op_def)

    def test_extra_msb_created(self):
        # 1+1=10: after finalise, result tree should encode 2 = binary 10.
        # The extra MSB (carry overflow) is a new node above the result node.
        # We don't have the op node anymore, so we look for a 2-node result tree.
        apply(self.g, self.op_def)
        # Find a node with a structural child that has a self-loop — that's
        # the extra MSB (1) above result (0). Result of 1+1 = 10 in binary.
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
        # Apply tombstone: operational self-loop on parent
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
        # child now tombstoned with no structural children → gc fires, removes child
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
        # Op node is gone. Find the result tree — should encode 2 = binary 10.
        # Look for a node with a self-loop (1) with a zero child.
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
        # 4 = binary 100 — a 1-node (MSB) with a zero child with a zero child.
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
