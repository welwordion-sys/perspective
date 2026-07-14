"""
tree_store.py — Serialisierung des Dispatch-Baums.

Zweck: build_dispatch_tree(252 Additionsregeln) kostet ~3.5s und wird heute in
JEDEM Testprozess neu bezahlt, obwohl das Ergebnis eine reine Funktion der
Regelmenge ist. Einmal bauen, auf Platte, danach laden.

Warum JSON und nicht pickle: der Baum ist bereits vollstaendig primitiv —
core_edges sind (int, int, str, None)-Tupel, _rule_map ist int->int,
fingerprints sind int->tuple. Keine Node-Objekte, keine Registry-Referenzen.
JSON ist damit ausreichend, menschenlesbar und ohne Pickle-Sicherheits- und
Versionsrisiko.

Zwei Fallen, die das Format aufloest:
  1. CoreNode.parent erzeugt einen Zyklus -> beim Laden rekonstruiert, nicht
     gespeichert.
  2. CoreNode.children mischt CoreNode-Objekte mit Regelnamen-Strings ->
     getrennt in "children" (rekursiv) und "members" (Strings).

INVALIDIERUNG: Der Baum gilt nur fuer die Regelmenge, aus der er gebaut wurde.
Gespeichert wird ein Fingerprint der Regelmenge (Namen + deren Kantenmuster);
load_tree() prueft ihn und verweigert einen Baum, dessen Regeln sich geaendert
haben. Ein stale Baum, der still geladen wird, waere ein Korrektheitsfehler,
kein Performance-Problem.

Nutzung:
    from tree_store import load_or_build
    tree = load_or_build(ADD_RULES, "addition_tree.json")

Run (baut/prueft den Additionsbaum): python3 grouping/tree_store.py
"""
from __future__ import annotations

import json
import os
import sys
import hashlib
import time

_R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in ['', 'grouping', 'builders', 'basic_machinery']:
    _q = os.path.join(_R, _p)
    if _q not in sys.path:
        sys.path.insert(0, _q)

from core_tree import CoreTree, CoreNode
from dispatch import build_dispatch_tree, _rule_edges

FORMAT_VERSION = 1


# ---------------------------------------------------------------- fingerprint

def ruleset_fingerprint(rule_names: list[str]) -> str:
    """Identitaet der Regelmenge: Namen UND deren Kantenmuster.

    Nur die Namen zu hashen reicht nicht — eine Regel kann unter gleichem Namen
    ihr Muster aendern (z.B. nach einem Fix in arithmetic_spine), und der Baum
    waere dann still falsch.
    """
    h = hashlib.sha256()
    for nm in sorted(rule_names):
        h.update(nm.encode())
        h.update(b'\x00')
        for e in sorted(_rule_edges(nm), key=repr):
            h.update(repr(e).encode())
            h.update(b'\x01')
    return h.hexdigest()


# ---------------------------------------------------------------- encode

def _enc_node(n: CoreNode) -> dict:
    """children wird als GEORDNETE, typisierte Sequenz gespeichert.

    Die Reihenfolge ist NICHT kosmetisch: _find_and_try laeuft children in
    dieser Reihenfolge ab und sperrt jede besuchte Regel im visited-Set. Eine
    Umsortierung (etwa: erst alle CoreNodes, dann alle Strings) aendert, welche
    Regel zuerst probiert wird, und damit das Dispatch-Ergebnis. Getrennte
    members/children-Listen zu speichern zerstoert genau diese Information.
    """
    return {
        "core_edges": [list(e) for e in n.core_edges],
        "fingerprints": [[k, list(v)] for k, v in n.fingerprints.items()],
        "children": [
            ["member", c] if isinstance(c, str) else ["node", _enc_node(c)]
            for c in n.children
        ],
    }


def dump_tree(tree: CoreTree, rule_names: list[str], path: str) -> None:
    blob = {
        "format_version": FORMAT_VERSION,
        "ruleset_fingerprint": ruleset_fingerprint(rule_names),
        "rule_count": len(rule_names),
        "min_ratio": tree.min_ratio,
        "cross_ref_min_delta": tree.cross_ref_min_delta,
        "root": _enc_node(tree.root) if tree.root else None,
        "rule_map": {nm: [[k, v] for k, v in m.items()]
                     for nm, m in tree._rule_map.items()},
        "rule_edges": {nm: [list(e) for e in es]
                       for nm, es in tree._rule_edges.items()},
        # _rule_delta MUSS gespeichert werden, nicht beim Laden abgeleitet.
        # Es ist zwar fuer 251/252 Regeln exakt aus _rule_map + _rule_edges
        # rekonstruierbar — aber NICHT fuer alle: eine Regel, die als erste in
        # einen (Teil-)Baum eingefuegt wird, bekommt in CoreTree.insert direkt
        # ({}, 0.0, set()) zugewiesen, ohne _update_delta_info zu durchlaufen.
        # _compute_delta_info liefert fuer dieselbe leere core_node_set aber
        # ratio=1.0 (alles ist Delta). Ableitung wuerde diesen Knoten also
        # still von 0.0 auf 1.0 aendern — und ratio steuert, ob eine Regel in
        # cross_reference() beruecksichtigt wird (>= cross_ref_min_delta).
        # Gemessen an add_finalise_1bit: 251/252 rekonstruierbar, 1 nicht.
        "rule_delta": {nm: [[[k, list(v)] for k, v in fp.items()],
                            ratio,
                            sorted(cns)]
                       for nm, (fp, ratio, cns) in tree._rule_delta.items()},
    }
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(blob, f)
    os.replace(tmp, path)   # atomar: ein abgebrochener Schreibvorgang darf
                            # keinen halben Baum hinterlassen


# ---------------------------------------------------------------- decode

def _dec_node(d: dict, parent: CoreNode | None) -> CoreNode:
    n = CoreNode.__new__(CoreNode)
    n.core_edges = {tuple(e) for e in d["core_edges"]}
    n.fingerprints = {k: tuple(v) for k, v in d["fingerprints"]}
    n.parent = parent
    n.children = []
    for kind, payload in d["children"]:
        if kind == "member":
            n.children.append(payload)
        else:
            n.children.append(_dec_node(payload, n))
    return n


def load_tree(path: str, rule_names: list[str]) -> CoreTree | None:
    """Laedt den Baum, ODER gibt None zurueck wenn er nicht passt.

    None heisst immer: neu bauen. Kein stiller Fallback auf einen falschen Baum.
    """
    try:
        with open(path) as f:
            blob = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None

    if blob.get("format_version") != FORMAT_VERSION:
        return None
    if blob.get("ruleset_fingerprint") != ruleset_fingerprint(rule_names):
        return None

    t = CoreTree(min_ratio=blob["min_ratio"],
                 cross_ref_min_delta=blob["cross_ref_min_delta"])
    t.root = _dec_node(blob["root"], None) if blob["root"] else None
    t._rule_map = {nm: {k: v for k, v in pairs}
                   for nm, pairs in blob["rule_map"].items()}
    t._rule_edges = {nm: [tuple(e) for e in es]
                     for nm, es in blob["rule_edges"].items()}
    t._rule_delta = {nm: ({k: tuple(v) for k, v in fp},
                          ratio,
                          set(cns))
                     for nm, (fp, ratio, cns) in blob["rule_delta"].items()}
    # _pairwise und _delta_cache werden bewusst NICHT gespeichert: reine
    # Caches, die sich bei Bedarf neu fuellen. _rule_delta ist kein Cache,
    # sondern Zustand aus dem Insert-Pfad (s.o.).
    return t


def load_or_build(rule_names: list[str], path: str, verbose: bool = False) -> CoreTree:
    t = load_tree(path, rule_names)
    if t is not None:
        if verbose:
            print(f"tree geladen aus {path}")
        return t
    if verbose:
        print(f"kein gueltiger baum in {path} — baue neu ...")
    t = build_dispatch_tree(rule_names)
    dump_tree(t, rule_names, path)
    return t


# ---------------------------------------------------------------- selftest

def _shape(n: CoreNode):
    """Strukturvergleich — ORDNUNGSSENSITIV.

    Eine fruehere Fassung sortierte members und trennte sie von den CoreNodes.
    Damit verglich sie genau die Information weg, die das Dispatch-Ergebnis
    bestimmt (children-Reihenfolge), und meldete PASS auf einem Baum, der
    anders dispatchte. Die Reihenfolge ist Teil der Struktur.
    """
    return (
        frozenset(n.core_edges),
        frozenset((k, v) for k, v in n.fingerprints.items()),
        tuple(c if isinstance(c, str) else _shape(c) for c in n.children),
    )


def _main():
    import os as _os

    import basic_machinery.operations as ops
    import builders.arithmetic_spine as _spine
    if 'bit_add_00_c0_cont_cont_2bit' not in ops._registry:
        _spine.register_all()

    ADD = sorted(n for n in ops._registry
                 if n.startswith('add_init') or n.startswith('bit_add') or 'finalise' in n)
    path = _os.path.join(_R, "grouping", "addition_tree.json")

    print(f"regeln: {len(ADD)}")

    t0 = time.perf_counter()
    built = build_dispatch_tree(ADD)
    t_build = time.perf_counter() - t0
    print(f"build : {t_build:.3f}s")

    dump_tree(built, ADD, path)
    size = _os.path.getsize(path) / 1024
    print(f"dump  : {size:.1f} KB -> {path}")

    t0 = time.perf_counter()
    loaded = load_tree(path, ADD)
    t_load = time.perf_counter() - t0
    print(f"load  : {t_load:.3f}s   ({t_build/t_load:.0f}x schneller)")

    # 1. Struktur identisch?
    assert _shape(built.root) == _shape(loaded.root), "STRUKTUR WEICHT AB"
    print("ok: baumstruktur identisch (cores, fingerprints, members, rekursiv)")

    # 2. rule_map identisch?
    assert built._rule_map == loaded._rule_map, "_rule_map WEICHT AB"
    print(f"ok: _rule_map identisch ({len(loaded._rule_map)} regeln)")

    # 2b. _rule_delta identisch? (kein Cache — Zustand aus dem Insert-Pfad)
    assert built._rule_delta == loaded._rule_delta, "_rule_delta WEICHT AB"
    print(f"ok: _rule_delta identisch ({len(loaded._rule_delta)} regeln)")

    # 2c. cross_reference() muss auf beiden Baeumen dasselbe tun.
    #     Genau hier schlug die Ableitungs-Variante fehl: eine Regel mit leerem
    #     _rule_map bekommt im Insert-Pfad ratio=0.0, abgeleitet waere es 1.0 —
    #     und ratio entscheidet ueber Teilnahme an cross_reference.
    import copy
    b2 = build_dispatch_tree(ADD)
    l2 = load_tree(path, ADD)
    n_b = b2.cross_reference()
    n_l = l2.cross_reference()
    assert n_b == n_l, f"cross_reference WEICHT AB: built={n_b} loaded={n_l}"
    assert _shape(b2.root) == _shape(l2.root), "baeume divergieren NACH cross_reference"
    print(f"ok: cross_reference identisch ({n_b} entdeckungen, struktur danach gleich)")

    # 3. parent-links rekonstruiert?
    def chk_parent(n, exp):
        assert n.parent is exp, "parent-link falsch"
        for c in n.children:
            if isinstance(c, CoreNode):
                chk_parent(c, n)
    chk_parent(loaded.root, None)
    print("ok: parent-links rekonstruiert")

    # 4. Invalidierung: geaenderte Regelmenge muss abgelehnt werden
    assert load_tree(path, ADD[:-1]) is None, "stale baum wurde AKZEPTIERT"
    print("ok: geaenderte regelmenge wird abgelehnt (kein stiller stale-load)")

    # 5. Dispatch-Aequivalenz auf echten States
    from basic_machinery.encoding import encode
    from basic_machinery.graph import PerspectiveGraph
    from basic_machinery.operations import apply
    from basic_machinery.match_view import derive_match_view, match_cut_at_edge
    from dispatch import dispatch

    def flat(g):
        for nm in ADD:
            r = ops._registry[nm]
            if match_cut_at_edge(r.graph2, g, list(g.nodes),
                                 view=derive_match_view(r.graph2)) is not None:
                return nm
        return None

    mism = fires = n = 0
    for a in range(3):
        for b in range(3):
            g = PerspectiveGraph(); encode(g, f'{a}+{b}={a+b}')
            for _ in range(20):
                truth = flat(g)
                if truth is None:
                    break
                gb = ops.snapshot(g); gl = ops.snapshot(g)
                rb = dispatch(gb, built)
                rl = dispatch(gl, loaded)
                n += 1
                if truth is not None:
                    fires += 1
                if rb != rl:
                    mism += 1
                    print(f"  MISMATCH {a}+{b}: built={rb} loaded={rl}")
                apply(g, ops._registry[truth])
    print(f"ok: dispatch identisch auf {n} states (fires={fires}, mismatches={mism})")
    assert fires > 0, "VACUOUS"
    assert mism == 0

    print()
    print(f"PASS — build {t_build:.3f}s wird zu load {t_load:.3f}s")


if __name__ == '__main__':
    _main()
