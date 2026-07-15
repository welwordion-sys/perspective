"""
matcher.py — optimierte Match-Maschinerie fuer Dispatch.

Ein Modul, kein Benchmark. Import:

    from matcher import Matcher
    m = Matcher(ADD_RULES)              # laedt/baut den Baum via tree_store
    rule_name = m.dispatch(graph)       # -> str | None

WAS HIER OPTIMIERT IST (und was gemessen NICHT hilft):

1. views memoisiert pro Regel — derive_match_view/_input_relations sind reine
   Funktionen von rule.graph2. Ohne das dominieren sie alles andere: flat_raw
   15.6s vs flat+memo 0.2s (77x). DAS ist der grosse Hebel, nicht grouping.

2. degree-index pro State — statt pro Regel pro Target einen O(|nodes|)-Scan
   zu fahren, EIN Durchlauf pro State, gebuendelt nach Grad-Signatur. Gemessen
   gab es nur 15 verschiedene Signaturen auf 3180 Bind-Targets (Faktor 212).

3. match_core statt find_core — find_core ist ein exhaustive seed-pair MCS
   finder (BAUkonstruktion: "welche Struktur haben zwei UNBEKANNTE Graphen
   gemeinsam"). Zur Dispatch-Zeit ist der Core BEKANNT; gesucht ist nur seine
   Einbettung. find_core im Dispatch-Pfad kostete 25x gegenueber flat; mit
   match_core gewinnt grouping 1.33x. Derselbe Baum, derselbe Mechanismus.

4. DEGRADATIONS-GUARD (siehe unten) — Cores werden uebersprungen, wenn sie zu
   wenig Regeln decken, um ihren Probe zu bezahlen.

SEEDING — die ID->Node-Bruecke (war der Bug):
   _rule_map mappt core_label -> rule_node_ID (int). view.bind_targets sind
   Node-OBJEKTE mit passender .id — dieselbe Nummerierung, andere
   Repraesentation. Ohne Uebersetzung greift `t in seed` (t=Node, keys=int)
   nie, das Seeding lief ins Leere und der gemessene Gewinn stammte
   ausschliesslich aus negativer Information. Bruecke: {n.id: n for n in
   view.bind_targets}, memoisiert pro Regel.

NICHT drin, weil gemessen wirkungslos:
   - Core-Match-Memoisierung ueber (core,state): core_cached war 0. visited
     besucht jeden Baumknoten pro Dispatch ohnehin nur einmal. Ueber States
     hinweg waere sie nicht gueltig (der Host aendert sich nach jedem apply).

WORAN DER GEWINN HAENGT (gemessen, nicht vermutet):
   invoc 2921 -> 197 (14.8x), aber consistent nur 12462 -> 11690 (1.07x).
   Grouping spart SETUP, nicht Suche: 187 Core-Misses erschlugen 4640
   Regelversuche. Der Traeger ist gruppenweite NEGATIVE INFORMATION.

DEGRADATIONS-VERHALTEN:
   Bei maximal verschiedenen Regeln teilt kein Paar einen Core. Der Baum wird
   flach (Wurzel + N Blaetter). Grouping probiert dann dieselben Regeln wie
   flat, zahlt aber zusaetzlich einen Core-Probe je Blatt — es ist flat PLUS
   Overhead, nicht flat. Der Kipppunkt liegt beim Verhaeltnis
   Probe-Kosten : uebersprungene-Regeln. Deshalb der Guard: ein Core, unter
   dem weniger als MIN_GROUP Regeln haengen, wird nicht geprobed, sondern
   seine Regeln direkt probiert. Damit degradiert grouping zu flat statt
   unter flat.

VORBEHALT: build_dispatch_tree ist prozessuebergreifend nicht-deterministisch
(PYTHONHASHSEED steuert eine Iterationsreihenfolge). Jeder Seed liefert eine
ANDERE, aber gueltige Zerlegung — drei Baeume, drei shape-hashes, identische
Dispatch-Folge und 0 mismatches. Die Baeume sind gleichwertig, nicht kaputt.
tree_store schreibt einen davon fest; das ist die Voraussetzung dafuer, dass
Messungen ueberhaupt gegen denselben Baum laufen.
"""
from __future__ import annotations

import os
import sys

_R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in ['', 'grouping', 'builders', 'basic_machinery']:
    _q = os.path.join(_R, _p)
    if _q not in sys.path:
        sys.path.insert(0, _q)

import basic_machinery.operations as ops
from basic_machinery.graph import Edge, EdgeType
from basic_machinery.match_view import (
    derive_match_view, _input_relations, real_total_degree,
)
from core_tree import CoreNode
from tree_store import load_or_build

_ETC = {e.name: e for e in EdgeType}

#: Ein Core lohnt sich erst ab so vielen Regeln darunter. Bei 1 kostet der
#: Probe mehr, als der Miss erspart (er erspart genau eine Regel).
MIN_GROUP = 2


class Matcher:
    """Dispatch ueber einen serialisierten CoreTree, mit Memoisierung.

    Aequivalent zu flat match-all: liefert dieselbe feuernde Regel wie ein
    linearer Scan in `rule_names`-Reihenfolge. Die Reihenfolge ist
    verhaltenswirksam (erster Treffer gewinnt), also ist rule_names Teil der
    Semantik, nicht Kosmetik.
    """

    def __init__(self, rule_names, tree_path=None, min_group=MIN_GROUP,
                 use_grouping=True):
        self.rules = list(rule_names)
        self.min_group = min_group
        self.use_grouping = use_grouping
        self._view = {}
        self._sat_cache = {}
        self._core = {}
        self._under = {}
        self.stats = dict(invoc=0, consistent=0, core_probe=0,
                          core_hit=0, core_miss=0, rules_skipped=0,
                          core_bypassed=0, verify=0)
        if tree_path is None:
            tree_path = os.path.join(_R, 'grouping', 'dispatch_tree.json')
        self.tree = load_or_build(self.rules, tree_path) if use_grouping else None
        for nm in self.rules:
            self._view_of(nm)

    # ---------- memo: views (reine fn von rule.graph2) ----------
    def _view_of(self, nm):
        v = self._view.get(nm)
        if v is None:
            g2 = ops._registry[nm].graph2
            mv = derive_match_view(g2)
            # by_id: die Bruecke von _rule_map's int-IDs zu den Node-Objekten,
            # die _match_rule als seed-keys erwartet. Reine Funktion der Regel.
            by_id = {n.id: n for n in mv.bind_targets}
            self._view[nm] = v = (mv, _input_relations(g2, mv), by_id)
        return v

    # ---------- memo: core-adjazenz (reine fn von core_edges) ----------
    def _core_of(self, node):
        k = id(node)
        c = self._core.get(k)
        if c is None:
            adj, deg = {}, {}
            for (s, t, et, _) in node.core_edges:
                adj.setdefault(s, []).append((t, et, 'out'))
                adj.setdefault(t, []).append((s, et, 'in'))
                deg.setdefault(s, {}); deg.setdefault(t, {})
                deg[s][(et, 'out')] = deg[s].get((et, 'out'), 0) + 1
                deg[t][(et, 'in')] = deg[t].get((et, 'in'), 0) + 1
            order = sorted(adj, key=lambda n: -len(adj[n]))
            self._core[k] = c = (adj, deg, order)
        return c

    def _members_under(self, node):
        k = id(node)
        m = self._under.get(k)
        if m is None:
            out = [c for c in node.children if isinstance(c, str)]
            for c in node.children:
                if isinstance(c, CoreNode):
                    out.extend(self._members_under(c))
            self._under[k] = m = out
        return m

    # ---------- per-state index ----------
    @staticmethod
    def _sig(exp):
        return tuple(sorted((str(k), n) for k, n in exp.items()))

    def _degree_index(self, graph):
        idx = {}
        for g in graph.nodes:
            idx.setdefault(self._sig(real_total_degree(g, graph)), []).append(g)
        return idx

    @staticmethod
    def _host_deg(g, graph):
        d = {}
        for e in graph.edges_from(g):
            k = (e.edge_type.name, 'out'); d[k] = d.get(k, 0) + 1
        for e in graph.edges_to(g):
            k = (e.edge_type.name, 'in'); d[k] = d.get(k, 0) + 1
        return d

    # ---------- core-einbettung (KEIN MCS) ----------
    def _match_core(self, node, graph, host_deg):
        adj, deg, order = self._core_of(node)
        if not order:
            return {}
        # HOTSPOT (gemessen: _match_core war 60% der dispatch-zeit, davon der
        # loewenanteil in diesem filter — 104387 generator-aufrufe bei 377
        # probes). Vorher wurde fuer JEDES core-label ueber ALLE host-knoten
        # iteriert und all(...) ausgewertet. Der bedarf need ist aber eine
        # reine funktion des cores, und die erfuellermenge je einzelner
        # anforderung (etype,richtung,>=n) ist eine reine funktion des STATE.
        # Also: pro state EINMAL je anforderung die knotenmenge bestimmen und
        # cachen, dann ist ein label-kandidatensatz nur noch ein
        # mengen-schnitt. Das ist dieselbe buendelung, die _degree_index fuer
        # die regeln macht — dort ==, hier >=.
        sat = self._sat_cache
        cand = {}
        for lbl in order:
            need = deg[lbl]
            if not need:
                cand[lbl] = list(graph.nodes)
                continue
            acc = None
            for k, v in need.items():
                key = (k, v)
                st = sat.get(key)
                if st is None:
                    st = frozenset(g for g in graph.nodes
                                   if host_deg[g].get(k, 0) >= v)
                    sat[key] = st
                acc = st if acc is None else (acc & st)
                if not acc:
                    return None
            if not acc:
                return None
            cand[lbl] = list(acc)
        mapping, reverse = {}, {}

        def ok(lbl, g):
            self.stats['consistent'] += 1
            if g in reverse:
                return False
            for (nbr, et, d) in adj[lbl]:
                if nbr in mapping:
                    if d == 'out':
                        if Edge(g, mapping[nbr], _ETC[et]) not in graph:
                            return False
                    elif Edge(mapping[nbr], g, _ETC[et]) not in graph:
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

    # ---------- regel-match ----------
    def _match_rule(self, nm, graph, deg_idx, seed=None):
        self.stats['invoc'] += 1
        view, rel, _by_id = self._view_of(nm)
        targets = list(view.bind_targets)
        cand_for = {}
        for t in targets:
            if seed and t in seed:
                # CUT-GENAUIGKEIT: der seed darf den degree-filter NICHT
                # umgehen. _match_core filtert mit >= (core-kanten sind eine
                # teilmenge der host-kanten), _match_rule verlangt aber
                # GLEICHHEIT der expected_degree. Ein seed-knoten kann also
                # mehr kanten haben, als die regel erlaubt. Ohne diese
                # pruefung machte der seed aus einem NICHT-match einen match:
                # add_init_00 matchte auf 0+1=1 (ohne seed: False, mit seed:
                # True) -> 27 mismatches, systematisch 00 statt 01/10.
                lst = deg_idx.get(self._sig(view.expected_degree[t]))
                if not lst or seed[t] not in lst:
                    return None
                cand_for[t] = [seed[t]]; continue
            lst = deg_idx.get(self._sig(view.expected_degree[t]))
            if not lst:
                return None
            cand_for[t] = lst
        seeded = [t for t in targets if seed and t in seed]
        order = seeded + sorted([t for t in targets if not (seed and t in seed)],
                                key=lambda t: len(cand_for[t]))
        result = {}

        def consistent(t, g, mapping, reverse):
            self.stats['consistent'] += 1
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

    # ---------- public ----------
    def dispatch(self, graph):
        if not self.use_grouping or self.tree is None or self.tree.root is None:
            return self.flat(graph)
        di = self._degree_index(graph)
        hd = {g: self._host_deg(g, graph) for g in graph.nodes}
        self._sat_cache = {}      # pro state: (anforderung) -> erfuellermenge
        return self._walk(self.tree.root, graph, di, hd, set(), {})

    def flat(self, graph):
        di = self._degree_index(graph)
        for nm in self.rules:
            if self._match_rule(nm, graph, di) is not None:
                return nm
        return None

    def _walk(self, node, graph, di, hd, visited, acc=None):
        under = self._members_under(node)

        # DEGRADATIONS-GUARD: ein Core unter min_group Regeln kann seinen
        # Probe nicht bezahlen — ein Miss erspart weniger Regelversuche, als
        # der Probe kostet. Ohne diesen Zweig waere grouping bei maximal
        # verschiedenen Regeln (flacher Baum, Gruppen der Groesse 1)
        # systematisch LANGSAMER als flat, nicht gleich schnell.
        if len(under) < self.min_group and node is not self.tree.root:
            self.stats['core_bypassed'] += 1
            nm_map = {}
        else:
            self.stats['core_probe'] += 1
            nm_map = self._match_core(node, graph, hd)
            if nm_map is None:
                self.stats['core_miss'] += 1
                self.stats['rules_skipped'] += len(under)
                return None
            self.stats['core_hit'] += 1
        # EBENEN (g_level/o_level): _rule_map[nm] ist die akkumulierte
        # korrespondenz ROOT-BIS-BLATT, nm_map bindet nur DIESEN knoten.
        # Naiv beide zu mischen seedet labels aus fremden ebenen gegen die
        # bindung dieser ebene -> falscher seed, gemessen 27 mismatches.
        # Darum: die bindungen entlang des pfades akkumulieren und nur
        # labels seeden, die auf diesem pfad tatsaechlich gebunden wurden.
        if acc is None:
            acc = {}
        acc = dict(acc)
        acc.update(nm_map)

        for c in node.children:
            if isinstance(c, CoreNode) and id(c) not in visited:
                visited.add(id(c))
                got = self._walk(c, graph, di, hd, visited, acc)
                if got is not None:
                    return got

        for nm in [c for c in node.children
                   if isinstance(c, str) and c not in visited]:
            visited.add(nm)
            _v, _r, by_id = self._view_of(nm)
            seed = {}
            for core_lbl, rule_lbl in self.tree._rule_map.get(nm, {}).items():
                if core_lbl in nm_map:
                    tgt = by_id.get(rule_lbl)      # int -> Node
                    if tgt is not None:
                        seed[tgt] = nm_map[core_lbl]
            if self._match_rule(nm, graph, di, seed=seed or None) is not None:
                return nm
        return None

    def reset_stats(self):
        for k in self.stats:
            self.stats[k] = 0
