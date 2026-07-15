"""
bench_serialized.py — der Test: serialized grouping vs flat, beide memoisiert.

VORGESCHICHTE (zurueckgezogen: ans_core_dominates):
Ein frueherer Lauf mass grouped+memo als 25x LANGSAMER und schrieb das dem
Mechanismus zu. Falsch: er rief find_core im Dispatch-Pfad auf. find_core ist
laut eigenem Docstring ein "exhaustive seed-pair MCS finder" — er sucht die
groesste gemeinsame Struktur zweier UNBEKANNTER Graphen. Das ist BAUKONSTRUKTION.
Zur Dispatch-Zeit ist der Core BEKANNT (node.core_edges, fix seit dem Bau);
gesucht ist nur die Einbettung eines bekannten Kantenmusters.

Dieser Test ersetzt find_core durch match_core(): gerichtete Einbettungssuche
mit Grad-Vorfilter, kein Seed-Paar-Enumerieren. Memoisiert wird alles, was
reine Funktion ist: views pro Regel, core-adjazenz pro Core, degree-index pro
State, core-match-ergebnis pro (core,state).

Baum kommt aus tree_store (load statt build).
Gezaehlt werden WORK-UNITS (consistent), nicht Invocations.
"""
from __future__ import annotations
import sys, os, time

_R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in ['', 'grouping', 'builders', 'basic_machinery']:
    sys.path.insert(0, os.path.join(_R, _p))

import basic_machinery.operations as ops
import builders.arithmetic_spine as _spine
if 'bit_add_00_c0_cont_cont_2bit' not in ops._registry:
    _spine.register_all()

from basic_machinery.encoding import encode
from basic_machinery.graph import PerspectiveGraph, Edge, EdgeType
from basic_machinery.operations import apply
from basic_machinery.match_view import (
    derive_match_view, _input_relations, real_total_degree,
    match_cut_at_edge as REAL,
)
from core_tree import CoreNode
from tree_store import load_or_build

ADD = sorted(n for n in ops._registry
             if n.startswith('add_init') or n.startswith('bit_add') or 'finalise' in n)
TREE_PATH = os.path.join(_R, 'grouping', 'addition_tree.json')
_ETC = {e.name: e for e in EdgeType}

W = {'consistent': 0, 'invoc': 0, 'core_probe': 0, 'core_hit': 0,
     'core_miss': 0, 'core_cached': 0, 'rules_skipped': 0}


def reset():
    for k in W:
        W[k] = 0


_VIEW = {}


def view_of(nm):
    v = _VIEW.get(nm)
    if v is None:
        g2 = ops._registry[nm].graph2
        mv = derive_match_view(g2)
        _VIEW[nm] = v = (mv, _input_relations(g2, mv))
    return v


def _sig(exp):
    return tuple(sorted((str(k), n) for k, n in exp.items()))


def degree_index(graph):
    idx = {}
    for g in graph.nodes:
        idx.setdefault(_sig(real_total_degree(g, graph)), []).append(g)
    return idx


_CORE = {}


def core_of(node):
    """Adjazenz + Grad-Profil. Reine Funktion von core_edges (fix nach Bau)."""
    k = id(node)
    c = _CORE.get(k)
    if c is None:
        adj, deg = {}, {}
        for (s, t, et, _) in node.core_edges:
            adj.setdefault(s, []).append((t, et, 'out'))
            adj.setdefault(t, []).append((s, et, 'in'))
            deg.setdefault(s, {}); deg.setdefault(t, {})
            deg[s][(et, 'out')] = deg[s].get((et, 'out'), 0) + 1
            deg[t][(et, 'in')] = deg[t].get((et, 'in'), 0) + 1
        order = sorted(adj, key=lambda n: -len(adj[n]))
        _CORE[k] = c = (adj, deg, order)
    return c


def _host_deg(g, graph):
    d = {}
    for e in graph.edges_from(g):
        d[(e.edge_type.name, 'out')] = d.get((e.edge_type.name, 'out'), 0) + 1
    for e in graph.edges_to(g):
        d[(e.edge_type.name, 'in')] = d.get((e.edge_type.name, 'in'), 0) + 1
    return d


def match_core(node, graph, host_deg):
    """Einbettung eines BEKANNTEN Kantenmusters. Kein MCS, kein Seed-Paar-Enum.
    Grad-Vorfilter mit >= (Core-Kanten sind Teilmenge der Host-Kanten)."""
    adj, deg, order = core_of(node)
    if not order:
        return {}
    cand = {}
    for lbl in order:
        need = deg[lbl]
        lst = [g for g in graph.nodes
               if all(host_deg[g].get(k, 0) >= v for k, v in need.items())]
        if not lst:
            return None
        cand[lbl] = lst
    mapping, reverse = {}, {}

    def ok(lbl, g):
        W['consistent'] += 1
        if g in reverse:
            return False
        for (nbr, et, d) in adj[lbl]:
            if nbr in mapping:
                if d == 'out':
                    if Edge(g, mapping[nbr], _ETC[et]) not in graph:
                        return False
                else:
                    if Edge(mapping[nbr], g, _ETC[et]) not in graph:
                        return False
        return True

    def bt(i):
        if i == len(order):
            return True
        lbl = order[i]
        for g in cand[lbl]:
            if ok(lbl, g):
                mapping[lbl] = g; reverse[g] = lbl
                if bt(i + 1):
                    return True
                del mapping[lbl]; del reverse[g]
        return False

    return dict(mapping) if bt(0) else None


def match_rule(nm, graph, deg_idx, seed=None):
    W['invoc'] += 1
    view, rel = view_of(nm)
    targets = list(view.bind_targets)
    cand_for = {}
    for t in targets:
        if seed and t in seed:
            cand_for[t] = [seed[t]]; continue
        lst = deg_idx.get(_sig(view.expected_degree[t]))
        if not lst:
            return None
        cand_for[t] = lst
    seeded = [t for t in targets if seed and t in seed]
    order = seeded + sorted([t for t in targets if not (seed and t in seed)],
                            key=lambda t: len(cand_for[t]))

    def consistent(t, g, mapping, reverse):
        W['consistent'] += 1
        if g in reverse:
            return False
        for (tn, et) in rel[t]:
            if tn in mapping and Edge(g, mapping[tn], et) not in graph:
                return False
        for src, lst in rel.items():
            if src in mapping:
                for (tn, et) in lst:
                    if tn == t and Edge(mapping[src], g, et) not in graph:
                        return False
        return True

    result = {}

    def crossing_ok(mapping):
        region = set(mapping.values())
        for t, g in mapping.items():
            exp = view.expected_crossing.get(t, {})
            real = {}
            for e in graph.edges_from(g):
                if e.source != e.target and e.target not in region:
                    k = (e.edge_type, 'out'); real[k] = real.get(k, 0) + 1
            for e in graph.edges_to(g):
                if e.source != e.target and e.source not in region:
                    k = (e.edge_type, 'in'); real[k] = real.get(k, 0) + 1
            if real != exp:
                return False
        return True

    def bt(d, mapping, reverse):
        if d == len(order):
            if not crossing_ok(mapping):
                return False
            result.update(mapping); return True
        t = order[d]
        for g in cand_for[t]:
            if consistent(t, g, mapping, reverse):
                mapping[t] = g; reverse[g] = t
                if bt(d + 1, mapping, reverse):
                    return True
                del mapping[t]; del reverse[g]
        return False

    return result if bt(0, {}, {}) else None


def flat_memo(graph):
    di = degree_index(graph)
    for nm in ADD:
        if match_rule(nm, graph, di) is not None:
            return nm
    return None


def _members_under(node):
    out = [c for c in node.children if isinstance(c, str)]
    for c in node.children:
        if isinstance(c, CoreNode):
            out.extend(_members_under(c))
    return out


def grouped(graph, tree):
    if tree.root is None:
        return None
    di = degree_index(graph)
    hd = {g: _host_deg(g, graph) for g in graph.nodes}
    return _walk(graph, tree, tree.root, di, hd, {}, set())


def _walk(graph, tree, node, di, hd, memo, visited):
    k = id(node)
    if k in memo:
        W['core_cached'] += 1
        nm_map = memo[k]
    else:
        W['core_probe'] += 1
        nm_map = match_core(node, graph, hd)
        memo[k] = nm_map
    if nm_map is None:
        W['core_miss'] += 1
        W['rules_skipped'] += len(_members_under(node))
        return None
    W['core_hit'] += 1
    for c in node.children:
        if isinstance(c, CoreNode) and id(c) not in visited:
            visited.add(id(c))
            got = _walk(graph, tree, c, di, hd, memo, visited)
            if got is not None:
                return got
    for nm in [c for c in node.children if isinstance(c, str) and c not in visited]:
        visited.add(nm)
        seed = {}
        for core_lbl, rule_lbl in tree._rule_map.get(nm, {}).items():
            if core_lbl in nm_map:
                seed[rule_lbl] = nm_map[core_lbl]
        if match_rule(nm, graph, di, seed=seed or None) is not None:
            return nm
    return None


def flat_raw(graph):
    for nm in ADD:
        g2 = ops._registry[nm].graph2
        if REAL(g2, graph, list(graph.nodes), view=derive_match_view(g2)) is not None:
            return nm
    return None


def collect():
    st = []
    for a in range(4):
        for b in range(4):
            g = PerspectiveGraph(); encode(g, f'{a}+{b}={a+b}')
            for _ in range(40):
                nm = flat_raw(g)
                if nm is None:
                    break
                st.append(ops.snapshot(g))
                apply(g, ops._registry[nm])
    return st


def run(fn, states):
    reset()
    t0 = time.perf_counter()
    res = [fn(s) for s in states]
    return res, time.perf_counter() - t0, dict(W)


def main():
    print("states sammeln ...")
    states = collect()
    truth = [flat_raw(s) for s in states]
    fires = sum(1 for x in truth if x is not None)
    print(f"rules={len(ADD)}  states={len(states)}  fires={fires}")

    t0 = time.perf_counter()
    tree = load_or_build(ADD, TREE_PATH, verbose=True)
    print(f"tree bereit in {time.perf_counter()-t0:.3f}s (serialisiert)")

    for nm in ADD:
        view_of(nm)

    r_f, t_f, w_f = run(flat_memo, states)
    r_g, t_g, w_g = run(lambda g: grouped(g, tree), states)
    m_f = sum(1 for a, b in zip(truth, r_f) if a != b)
    m_g = sum(1 for a, b in zip(truth, r_g) if a != b)

    print()
    print(f"  flat+memo     wall={t_f:7.3f}s  consistent={w_f['consistent']:7d}  invoc={w_f['invoc']:6d}")
    print(f"  grouped+memo  wall={t_g:7.3f}s  consistent={w_g['consistent']:7d}  invoc={w_g['invoc']:6d}")
    print(f"                core probe={w_g['core_probe']} cached={w_g['core_cached']} "
          f"hit={w_g['core_hit']} miss={w_g['core_miss']} regeln_uebersprungen={w_g['rules_skipped']}")
    print()
    print(f"aequivalenz: flat mism={m_f}  grouped mism={m_g}")
    if fires == 0:
        print("VACUOUS"); sys.exit(1)
    if m_f or m_g:
        print("FAIL — nicht aequivalent"); sys.exit(1)
    print()
    print("=== ERGEBNIS (>1 = grouping gewinnt) ===")
    print(f"  wall       {t_f/t_g:.2f}x")
    print(f"  consistent {w_f['consistent']/w_g['consistent']:.2f}x")
    print(f"  invoc      {w_f['invoc']/w_g['invoc']:.2f}x")
    print("EQUIVALENT")


if __name__ == '__main__':
    main()
