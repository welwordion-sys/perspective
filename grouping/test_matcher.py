"""
test_matcher.py — Aequivalenz + Degradations-These.

Prueft Svens These: bei maximal verschiedenen Graphen muss grouping zu
simplem per-rule matching degradieren. Gemessen wird an einer echten
Regel-Teilmenge mit minimaler Core-Ueberlappung, nicht an Synthetik.
"""
import sys, os, time, random
_R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in ['', 'grouping', 'builders', 'basic_machinery']:
    sys.path.insert(0, os.path.join(_R, _p))

import basic_machinery.operations as ops
import builders.arithmetic_spine as _spine
if 'bit_add_00_c0_cont_cont_2bit' not in ops._registry:
    _spine.register_all()

from basic_machinery.encoding import encode
from basic_machinery.graph import PerspectiveGraph
from basic_machinery.operations import apply
from basic_machinery.match_view import derive_match_view, match_cut_at_edge as REAL
from matcher import Matcher

ADD = sorted(n for n in ops._registry
             if n.startswith('add_init') or n.startswith('bit_add') or 'finalise' in n)


def flat_raw(g, rules):
    for nm in rules:
        g2 = ops._registry[nm].graph2
        if REAL(g2, g, list(g.nodes), view=derive_match_view(g2)) is not None:
            return nm
    return None


def collect(rules, n=4):
    st = []
    for a in range(n):
        for b in range(n):
            g = PerspectiveGraph(); encode(g, f'{a}+{b}={a+b}')
            for _ in range(40):
                nm = flat_raw(g, rules)
                if nm is None:
                    break
                st.append(ops.snapshot(g))
                apply(g, ops._registry[nm])
    return st


def bench(m, states, use_grouping):
    m.use_grouping = use_grouping
    m.reset_stats()
    t0 = time.perf_counter()
    res = [m.dispatch(s) for s in states]
    return res, time.perf_counter() - t0, dict(m.stats)


def main():
    print("=" * 62)
    print("TEIL 1 — volle Regelmenge (hohe Core-Ueberlappung)")
    print("=" * 62)
    states = collect(ADD)
    truth = [flat_raw(s, ADD) for s in states]
    fires = sum(1 for x in truth if x is not None)
    m = Matcher(ADD, tree_path='/tmp/full_tree.json')

    r_f, t_f, s_f = bench(m, states, False)
    r_g, t_g, s_g = bench(m, states, True)
    mm_f = sum(1 for a, b in zip(truth, r_f) if a != b)
    mm_g = sum(1 for a, b in zip(truth, r_g) if a != b)

    print(f"states={len(states)} fires={fires} rules={len(ADD)}")
    print(f"  flat     {t_f:6.3f}s  invoc={s_f['invoc']:5d} consistent={s_f['consistent']:6d}")
    print(f"  grouped  {t_g:6.3f}s  invoc={s_g['invoc']:5d} consistent={s_g['consistent']:6d}")
    print(f"           probe={s_g['core_probe']} hit={s_g['core_hit']} miss={s_g['core_miss']} "
          f"bypass={s_g['core_bypassed']} skipped={s_g['rules_skipped']}")
    print(f"  speedup  {t_f/t_g:.2f}x   mismatches: flat={mm_f} grouped={mm_g}")
    assert mm_f == 0 and mm_g == 0, "NICHT AEQUIVALENT"
    assert fires > 0, "VACUOUS"

    print()
    print("=" * 62)
    print("TEIL 2 — Degradation: maximal verschiedene Regeln")
    print("=" * 62)
    print("Svens These: bei maximal verschiedenen Graphen muss grouping zu")
    print("simplem per-rule matching degradieren.")
    print()

    # Teilmenge nach TATSAECHLICHER Core-Ueberlappung waehlen, nicht nach
    # Namen: greedy jene Regeln, deren Kantenmuster am wenigsten mit den
    # bereits gewaehlten teilen (Jaccard ueber die Kantenmengen).
    from dispatch import _rule_edges
    E = {nm: frozenset(_rule_edges(nm)) for nm in ADD}

    def jac(a, b):
        u = len(a | b)
        return len(a & b) / u if u else 0.0

    diverse = [ADD[0]]
    while len(diverse) < 24:
        best, bs = None, 2.0
        for nm in ADD:
            if nm in diverse:
                continue
            worst = max(jac(E[nm], E[d]) for d in diverse)
            if worst < bs:
                best, bs = nm, worst
        if best is None:
            break
        diverse.append(best)
    diverse = sorted(diverse)
    import itertools
    js = [jac(E[a], E[b]) for a, b in itertools.combinations(diverse, 2)]
    print(f"diverse Teilmenge: {len(diverse)} Regeln, "
          f"paarweise Jaccard max={max(js):.2f} mittel={sum(js)/len(js):.2f}")
    jf = [jac(E[a], E[b]) for a, b in itertools.combinations(ADD[:24], 2)]
    print(f"  (Vergleich: erste 24 Regeln der vollen Menge, "
          f"max={max(jf):.2f} mittel={sum(jf)/len(jf):.2f})")

    st2 = collect(diverse, n=3)
    if not st2:
        print("  (keine states — diverse menge feuert nicht; test uebersprungen)")
        return
    tr2 = [flat_raw(s, diverse) for s in st2]
    f2 = sum(1 for x in tr2 if x is not None)
    m2 = Matcher(diverse, tree_path='/tmp/div_tree.json')

    from core_tree import CoreNode
    def count_nodes(n):
        return 1 + sum(count_nodes(c) for c in n.children
                       if isinstance(c, CoreNode))
    nodes = count_nodes(m2.tree.root)
    root_mem = len([c for c in m2.tree.root.children if isinstance(c, str)])
    print(f"Baum: {nodes} core-knoten fuer {len(diverse)} regeln, "
          f"{root_mem} direkt an der wurzel")

    a_f, u_f, w_f = bench(m2, st2, False)
    a_g, u_g, w_g = bench(m2, st2, True)
    e_f = sum(1 for a, b in zip(tr2, a_f) if a != b)
    e_g = sum(1 for a, b in zip(tr2, a_g) if a != b)

    print(f"states={len(st2)} fires={f2}")
    print(f"  flat     {u_f:6.3f}s  invoc={w_f['invoc']:5d}")
    print(f"  grouped  {u_g:6.3f}s  invoc={w_g['invoc']:5d}")
    print(f"           probe={w_g['core_probe']} hit={w_g['core_hit']} miss={w_g['core_miss']} "
          f"bypass={w_g['core_bypassed']} skipped={w_g['rules_skipped']}")
    print(f"  speedup  {u_f/u_g:.2f}x   mismatches: flat={e_f} grouped={e_g}")
    assert e_f == 0 and e_g == 0, "NICHT AEQUIVALENT (divers)"

    print()
    print("BEFUND:")
    ratio = u_f / u_g
    if ratio > 1.05:
        print(f"  grouping gewinnt noch ({ratio:.2f}x) — die Teilmenge teilt")
        print("  mehr Struktur als 'maximal verschieden'.")
    elif ratio > 0.95:
        print(f"  grouping == flat ({ratio:.2f}x). These BESTAETIGT: degradiert")
        print("  zu per-rule matching, ohne darunter zu fallen.")
    else:
        print(f"  grouping FAELLT UNTER flat ({ratio:.2f}x) — der guard reicht")
        print("  nicht; probe-kosten uebersteigen den nutzen.")
    print()
    print("PASS")


if __name__ == '__main__':
    main()
