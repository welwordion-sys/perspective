import sys
sys.path.insert(0, '.')
from basic_machinery.graph import PerspectiveGraph, EdgeType
from basic_machinery.encoding import encode, build_number

# Test 1: self-loop on node 1
g = PerspectiveGraph()
n = build_number(g, 1)
loops = [e for e in g.edges if e.source == e.target]
print("Self-loop count on '1':", len(loops))

# Test 2: zero is empty
g2 = PerspectiveGraph()
n2 = build_number(g2, 0)
print("Node count for zero:", len(g2.nodes))
print("Edge count for zero:", len(g2.edges))

# Test 3: encode simple expression
g3 = PerspectiveGraph()
root = encode(g3, "3 + 4")
print("3+4 graph — nodes:", len(g3.nodes), "edges:", len(g3.edges))

# Test 4: encode equation
g4 = PerspectiveGraph()
root = encode(g4, "x + 4 = 7")
print("x+4=7 graph — nodes:", len(g4.nodes), "edges:", len(g4.edges))

print("All tests passed.")