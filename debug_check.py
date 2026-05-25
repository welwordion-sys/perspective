from basic_machinery.graph import PerspectiveGraph, EdgeType
from basic_machinery.encoding import build_number, build_operator, connect_operands
from basic_machinery.operations import apply, lookup, match, _apply_pass
import basic_machinery.arithmetic

g = PerspectiveGraph()
lr, ll = build_number(g, 2)
rr, rl = build_number(g, 1)
op, _ = build_operator(g, '+', finished=False)
connect_operands(g, op, lr, ll, rr, rl)

print('\n--- BEFORE ---')
for node in sorted(g.nodes, key=lambda n: n.id):
    s = [e.target.id for e in g.edges if e.source == node and e.edge_type.name == 'STRUCTURAL']
    o = [e.target.id for e in g.edges if e.source == node and e.edge_type.name == 'OPERATIONAL']
    if s or o:
        print(f'  {node.id}: S→{s} O→{o}')
print(f'total: {len(list(g.nodes))} nodes {len(list(g.edges))} edges')

op_def = lookup('add_init_01')
result = match(op_def.pattern, g)
print(f'\nPattern match: {result.success}')

if result.success:
    print(f'graph2s nodes: {len(list(op_def.graph2s.nodes))}')
    print(f'graph2s edges: {len(list(op_def.graph2s.edges))}')
    has_out = set()
    for e in op_def.graph2s.edges:
        if e.edge_type.name == 'OPERATIONAL':
            has_out.add(e.source.id)
    print(f'graph2s OPERATIONAL edge sources: {sorted(has_out)}')

    updated_map = _apply_pass(g, result.node_map, op_def.graph2s)
    print(f"updated_map: { {k.id: v.id for k, v in updated_map.items()} }")
    print(f'\n--- AFTER PASS 1 ---')
    for node in sorted(g.nodes, key=lambda n: n.id):
        s = [e.target.id for e in g.edges if e.source == node and e.edge_type.name == 'STRUCTURAL']
        o = [e.target.id for e in g.edges if e.source == node and e.edge_type.name == 'OPERATIONAL']
        if s or o:
            print(f'  {node.id}: S→{s} O→{o}')
    print(f'total: {len(list(g.nodes))} nodes {len(list(g.edges))} edges')
    print(f'updated_map values: {sorted(v.id for v in updated_map.values())}')
    print(f'updated_map size: {len(updated_map)}')