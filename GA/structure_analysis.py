"""
structure_analysis.py — Strukturensuche und Bezugsklasse

=============================================================================
ZWECK, VERDRAHTUNGSSTATUS, ABHÄNGIGKEITEN   (Pflichtangabe, meta.workflow)
=============================================================================
ZWECK
    Strukturen in einem Graphen finden, gerichtet korrelieren und die
    Wahrscheinlichkeit einer gefundenen Struktur exakt bestimmen. Drei
    Verwendungen, nach Rang: (1) Strukturen für Fitnessfunktion UND
    Rekombination, (2) Informationsgehalt einer Ebene, (3) Vorarbeit zur
    Regelsuche unter der DAG-Methode.

VERDRAHTUNGSSTATUS
    MODULE-ONLY — NICHT AUF DEM SOLVE-PFAD.
    Nichts ruft dieses Modul auf. Es ist Werkzeug für einen GA, der noch nicht
    existiert. Zum Verdrahten fehlt: die Fitness-Schnittstelle (§7 des
    Gesamtdesigns) und der GA-Lauf selbst (§3).
    Nur `test_structure_analysis.py` ruft es auf, und das ist ein Test, kein Pfad.

ABHÄNGIGKEITEN (müssen vorhanden sein, sonst läuft nichts)
    basic_machinery/graph.py   -> Edge, EdgeType, Node, PerspectiveGraph
    basic_machinery/__init__.py
    Sonst nur Standardbibliothek. graph.py ist selbst eigenständig
    (dataclasses, enum, typing) und braucht den Rest des Repos nicht.

WAS DIESES MODUL ERSETZT UND WARUM
    Ersetzt genetic_algorithm.py (2026-08-05, gelöscht). Jene Datei enthielt 20
    Definitionen, von denen nur 6 im abgestimmten Pseudocode standen; der Rest
    war teils Festlegung ohne Pseudocode, teils frei erfunden — darunter eine
    multiplizierte Gesamtbewertung und eine Trennschärfe-Kennzahl, die nie
    besprochen waren. Sie definierte außerdem eigene Graph-/Level-/Travelpath-
    Typen, obwohl PerspectiveGraph und LayeredGraph existieren und reicher sind
    (Provenienz, TravelType). Diese Datei enthält nur Abgestimmtes und baut auf
    den echten Typen auf.

=============================================================================
WAS HIER DRIN IST — und was absichtlich NICHT
=============================================================================
ABGESTIMMT (Pseudocode vorhanden, strukturanalyse_design.md):
    find_structures, form, classify, node_index, touching, correlate

VON SVEN FESTGELEGT (Substanz seine, Pseudocode fehlte):
    medium_has_self_loops, form_spectrum, form_entropy,
    reference_class_size, structure_probability

BEWUSST NICHT ENTHALTEN — siehe die DESIGNED-NOT-BUILT-Marker am Dateiende.

=============================================================================
GRUNDENTSCHEIDUNGEN
=============================================================================
* Budget zählt NUR Innenkanten. Zählte man Außenkanten mit, könnte ein Knoten mit
  mehr als budget Kanten nie Teil irgendeiner Struktur sein.
* Kreuzungen beschränken nie die Aufzählung, nur die Klassifikation am Ende.
* Identität OHNE Kreuzungen, damit Formen zusammenfallen und Häufigkeit zählbar
  wird. Kreuzungen dienen der Bewertung.
* Reihenfolge: (1) finden, (2) per Korrelation zusammensetzen, (3) klassifizieren.
* Max-k ist ein Leistungsdeckel, keine systematische Tatsache.
* Knoten sind nur durch ihre Struktur definiert, also ununterscheidbar.

ZWEI GETRENNTE WAHRSCHEINLICHKEITSFRAGEN — nicht vermischen:
  (a) beim Zusammensetzen: gehören diese Teile zusammen?  Zwischenbuchhaltung,
      darf ungenau sein  -> correlate() liefert Deckung und Zonengröße
  (b) die Endstruktur: wie wahrscheinlich ist sie?  exakt, analytisch
      -> structure_probability()

ACHTUNG bei PerspectiveGraph: `neighbors()` ist GERICHTET (nur Ziele ausgehender
Kanten). Für das Wachsen braucht es ungerichtete Nachbarschaft — dafür
undirected_adjacency().
"""

from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from math import comb, factorial
from typing import Iterable, Sequence

from basic_machinery.graph import Edge, EdgeType, Node, PerspectiveGraph

NodeSet = frozenset          # frozenset[Node]
Form = tuple


# =============================================================================
# Hilfsmittel auf PerspectiveGraph
# =============================================================================

def undirected_adjacency(g: PerspectiveGraph) -> dict[Node, NodeSet]:
    """Ungerichtete Nachbarschaft. Selbstschleifen verbinden nichts und zählen
    hier NICHT — sie zählen aber sehr wohl als Innenkante (siehe n_inner)."""
    nb: dict[Node, set[Node]] = {n: set() for n in g.nodes}
    for e in g.edges:
        if e.source != e.target:
            nb[e.source].add(e.target)
            nb[e.target].add(e.source)
    return {n: frozenset(v) for n, v in nb.items()}


def inner_edges(g: PerspectiveGraph, sub: NodeSet) -> list[Edge]:
    """Kanten mit BEIDEN Enden in sub. subgraph() macht genau das."""
    return list(g.subgraph(set(sub)).edges)


def n_inner(g: PerspectiveGraph, sub: NodeSet) -> int:
    return len(inner_edges(g, sub))


def crossings(g: PerspectiveGraph, sub: NodeSet) -> list[tuple[Node, EdgeType, str]]:
    """Außenkanten: genau ein Ende in sub. (knoten_innen, typ, richtung)."""
    out = []
    for e in g.edges:
        if e.source == e.target:
            continue
        if e.source in sub and e.target not in sub:
            out.append((e.source, e.edge_type, "out"))
        elif e.target in sub and e.source not in sub:
            out.append((e.target, e.edge_type, "in"))
    return out


def frontier(g: PerspectiveGraph, sub: NodeSet,
             nb: dict[Node, NodeSet]) -> set[Node]:
    f: set[Node] = set()
    for n in sub:
        f |= nb[n]
    return f - set(sub)


def medium_has_self_loops(g: PerspectiveGraph) -> bool:
    """Ob Selbstschleifen Kantenplätze sind, wird AUS DEM MEDIUM abgeleitet, nicht
    frei gesetzt. Wirkt erst bei kantenreicheren Kernen: bei k=5, e=5 halbiert ihr
    Wegfall die Formenzahl (gemessen 6742 -> 3744); bei (4,3) und (5,4) ändert es
    nichts, weil vier Kanten auf fünf Knoten für Zusammenhang schleifenfrei sein
    müssen."""
    return any(e.source == e.target for e in g.edges)


def edge_types_in(g: PerspectiveGraph) -> tuple[EdgeType, ...]:
    """Zahl der Kantentypen ebenfalls aus dem Medium."""
    return tuple(sorted({e.edge_type for e in g.edges}, key=lambda t: t.value))


# =============================================================================
# Phase 1 — Strukturen finden
# =============================================================================

def find_structures(g: PerspectiveGraph, budget: int
                    ) -> tuple[set[NodeSet], set[NodeSet]]:
    """Alle zusammenhängenden Strukturen mit <= budget INNENKANTEN.

    Gibt (alle, max_k). max_k = die nicht weiter erweiterbaren.

    Der Duplikattest IST die Mengensemantik: a+bc und ab+c ergeben dieselbe
    Knotenmenge und fallen beim Einfügen zusammen. Ein zusätzliches
    `neu - alle` fängt gemessen NULL weitere, weil nur gleich große kollidieren
    können — daher nicht enthalten.

    Kosten werden von der KANTENDICHTE getrieben, nicht der Knotenzahl:
    gemessen 29 Knoten / Größe 8 -> 439 Gruppen dünn, 2,4 Mio dicht.
    """
    nb = undirected_adjacency(g)
    level: set[NodeSet] = {frozenset([n]) for n in g.nodes}
    allg: set[NodeSet] = set(level)

    while level:
        nxt: set[NodeSet] = set()
        for s in level:
            for u in frontier(g, s, nb):
                cand = frozenset(s | {u})
                if n_inner(g, cand) <= budget:
                    nxt.add(cand)
        nxt -= allg
        if not nxt:
            break
        allg |= nxt
        level = nxt

    max_k = {s for s in allg
             if all(n_inner(g, frozenset(s | {u})) > budget
                    for u in frontier(g, s, nb))}
    return allg, max_k


# =============================================================================
# Phase 2 — Form und Korrelation
# =============================================================================

def form(g: PerspectiveGraph, sub: NodeSet) -> Form:
    """Kanonische Form durch schrittweise Verfeinerung.

    NICHT alle Permutationen durchprobieren — das ist fakultativ und bricht ab
    k~7 zusammen (belegt: Abbruch bei Verbünden von 10 Knoten).

    Identität OHNE Kreuzungen. Für die schnittgenaue Variante siehe classify().

    EINSCHRÄNKUNG: starke, aber keine perfekte Unterscheidung; kann in seltenen
    Fällen zwei Formen zusammenwerfen. Automorphismen liefert sie NICHT — die
    fehlen für die analytische Zählung (offener Punkt).
    """
    ie = inner_edges(g, sub)
    lab = {n: "0" for n in sub}
    for _ in range(len(sub)):
        new = {}
        for n in sub:
            sig = []
            for e in ie:
                if e.source == e.target == n:
                    sig.append(("self", e.edge_type.value))
                elif e.source == n:
                    sig.append(("out", e.edge_type.value, lab[e.target]))
                elif e.target == n:
                    sig.append(("in", e.edge_type.value, lab[e.source]))
            payload = lab[n] + "|" + repr(sorted(sig))
            new[n] = hashlib.blake2b(payload.encode(), digest_size=6).hexdigest()
        if new == lab:
            break
        lab = new
    return (len(sub),
            tuple(sorted(lab.values())),
            tuple(sorted((lab[e.source], lab[e.target], e.edge_type.value)
                         for e in ie)))


def classify(g: PerspectiveGraph, sub: NodeSet) -> tuple[Form, tuple]:
    """Phase 3: schnittgenau — Form PLUS Außensignatur.

    Erst hier kommen Kreuzungen ins Spiel. Der Transitiongraph zeichnet
    Strukturen bereits innen/außen getrennt auf, daher ist diese Klassifikation
    teilweise für Inputgraph-Suche und Kernsuche wiederverwendbar.
    """
    cr: dict[tuple, int] = defaultdict(int)
    for _, t, d in crossings(g, sub):
        cr[(t.value, d)] += 1
    return form(g, sub), tuple(sorted(cr.items()))


def group_by_form(g: PerspectiveGraph, structures: Iterable[NodeSet]
                  ) -> dict[Form, list[NodeSet]]:
    out: dict[Form, list[NodeSet]] = defaultdict(list)
    for s in structures:
        out[form(g, s)].append(s)
    return dict(out)


def node_index(structures: Sequence[NodeSet]) -> dict[Node, set[int]]:
    """Buchführung: Knoten -> welche Strukturen ihn enthalten. Liefert die
    berührenden Strukturen direkt, statt alle Paare auf Schnittmengen zu testen.
    Gemessen nur 1,2x auf kleinem Graphen — zahlt sich erst bei Größe aus."""
    idx: dict[Node, set[int]] = defaultdict(set)
    for i, s in enumerate(structures):
        for n in s:
            idx[n].add(i)
    return idx


def touching(g: PerspectiveGraph, structures: Sequence[NodeSet],
             idx: dict[Node, set[int]], i: int,
             nb: dict[Node, NodeSet]) -> set[int]:
    """Strukturen, die structures[i] BERÜHREN — überlappend ODER benachbart.

    Überlappung und Nachbarschaft schließen sich NICHT aus: gemessen sind
    1590 von 1896 Kandidaten beides. EINE Bedingung, nicht zwei Fälle.
    """
    o = structures[i]
    reach = set(o) | frontier(g, o, nb)
    cand: set[int] = set()
    for n in reach:
        cand |= idx[n]
    cand.discard(i)
    return cand


@dataclass
class Correlation:
    """GERICHTET: von Form A auf Verbundform. A->B und B->A sind verschieden.

    Gemessen: eine Seite 100%, die andere 44-56%. Beispiel: A ist 19x das Delta
    eines Kerns und 1x zufällige Übereinstimmung.

    Die drei Zahlen werden NICHT zu einer Bewertung verrechnet — wie sie zu
    verrechnen sind, ist offen (§16.6). Wer ordnen will, ordnet selbst.
    """
    source: Form
    joint: Form
    coverage: float
    n_occurrences: int
    mean_zone: float
    joint_size: int


def correlate(g: PerspectiveGraph, max_k: Sequence[NodeSet],
              min_share: float = 0.02) -> list[Correlation]:
    """Setzt Strukturen der Größe k+1 bis 2k in EINEM Durchlauf zusammen.

    Schnittmenge leer  -> Verbund hat Größe 2k
    Schnittmenge m > 0 -> Verbund hat Größe 2k-m

    KEIN Zusammenhangstest: berühren sich zwei je zusammenhängende Strukturen,
    hängt die Vereinigung zwangsläufig zusammen (gemessen: 0 von 1896
    Kandidaten unzusammenhängend). Der Test war reine Rechenzeit.

    KEIN `i<j`-Filter. Er stand hier mit der Begründung „a+b und b+a sind
    derselbe Verbund". Der VERBUND ist derselbe — die KORRELATION nicht: sie ist
    gerichtet (siehe Correlation). Berührten sich zwei Strukturen, schrieb der
    Filter den Verbund nur der Form mit dem KLEINEREN Index gut; die
    Gegenrichtung entfiel. Welche Hälfte überlebte, entschied die willkürliche
    Indexvergabe.

    Gemessen (abschalt_correlate_ij.py), fünf Indexvergaben auf demselben
    Substrat:
        mit  i<j : 599–669 Korrelationen, 12–19 asymmetrische Paare
        ohne i<j : 1.122 Korrelationen, 36 asymmetrische Paare — jedes Mal
    Die alten Zahlen 618/19 waren kein Messwert, sondern ein Artefakt der
    Hash-Reihenfolge. Dass sie stabil AUSSAHEN, lag nur daran, dass Repo-Node
    deterministisch hasht.

    Entdoppelt wird ohnehin schon: `hits[f]` ist eine MENGE von
    Vorkommensindizes, `a+b` und `b+a` fallen dort von selbst zusammen.

    min_share = Mindestanteil am Gesamtaufkommen, aufgerundet auf ganze n.
    Volle Deckung ist ZU STRENG — Kerngruppen sind per Definition mit
    verschiedenen Strukturen verbunden.
    Gemessen bei 56 Strukturen: 1% -> 35 von 35 Formen, 2% -> 16, 5% -> 5, 10% -> 0.
    """
    max_k = list(max_k)
    nb = undirected_adjacency(g)
    idx = node_index(max_k)
    by_form = group_by_form(g, max_k)
    pos = {s: i for i, s in enumerate(max_k)}
    threshold = max(1, math.ceil(len(max_k) * min_share))

    out: list[Correlation] = []
    for A, occs in by_form.items():
        if len(occs) < threshold:
            continue
        hits: dict[Form, set[int]] = defaultdict(set)
        zones: dict[Form, list[int]] = defaultdict(list)
        for k, o in enumerate(occs):
            i = pos[o]
            for j in touching(g, max_k, idx, i, nb):
                partner = max_k[j]
                f = form(g, frozenset(o | partner))
                hits[f].add(k)
                zones[f].append(len(set(partner) - set(o)))
        for f, ks in hits.items():
            out.append(Correlation(
                source=A, joint=f,
                coverage=len(ks) / len(occs),
                n_occurrences=len(occs),
                mean_zone=sum(zones[f]) / len(zones[f]),
                joint_size=f[0]))
    return out


# =============================================================================
# Informationsgehalt einer Ebene
# =============================================================================

def form_spectrum(g: PerspectiveGraph, budget: int) -> dict[Form, int]:
    """Formenverteilung der Max-k-Strukturen: Form -> Anzahl Stellen."""
    _, max_k = find_structures(g, budget)
    spec: dict[Form, int] = defaultdict(int)
    for s in max_k:
        spec[form(g, s)] += 1
    return dict(spec)


def form_entropy(g: PerspectiveGraph, budget: int) -> float:
    """Shannon-Entropie der Formenverteilung. Höher = chaotischer.

    Das ist die NEGATIVSEITE für Arithmetik: ein chaotischer Graph hat messbar
    mehr Entropie als ein strukturierter.

    Gemessen: der echte Kodierungsgraph erzeugt 35 verschiedene Formen, ein
    absolut zufälliger mit gleicher Knoten- und Kantenzahl 82,8-85,9. Entropie
    strukturiert 4,99 gegen chaotisch 6,32. Die EINSCHRÄNKUNG des Formenraums
    ist die Information, die die Kodierung trägt.
    """
    spec = form_spectrum(g, budget)
    n = sum(spec.values())
    if n == 0:
        return 0.0
    return -sum((c / n) * math.log2(c / n) for c in spec.values())


# =============================================================================
# Bezugsklasse einer Einzelstruktur — exakt, keine Stichprobe
# =============================================================================
#
# Modell: randkantenfreier Kern, ZUSAMMENHÄNGEND, keine disjunkten Graphen,
# PLUS kantenzahl-erhaltende Erweiterung — j angehängte Knoten mit je EINER
# Kante, j = Zahl der Randkanten, nur an Kernknoten (keine Ketten untereinander).
#
# Max-k ist ein Leistungsdeckel und steckt NICHT in der Endstruktur. Deshalb ist
# die Endauswertung analytisch möglich — die frühere Stichprobe war eine Notlösung
# für ein Problem, das nur durch das Vermischen der zwei Fragen entstand.

def _slots(k: int, n_types: int, self_loops: bool) -> list[tuple[int, int, int]]:
    return [(u, v, t) for u in range(k) for v in range(k)
            for t in range(n_types) if u != v or self_loops]


def _connected(k: int, edges: Sequence[tuple[int, int, int]]) -> bool:
    if k <= 1:
        return True
    adj: dict[int, set[int]] = defaultdict(set)
    for u, v, _ in edges:
        if u != v:
            adj[u].add(v)
            adj[v].add(u)
    seen, st = {0}, [0]
    while st:
        x = st.pop()
        for y in adj[x] - seen:
            seen.add(y)
            st.append(y)
    return len(seen) == k


def _canon_indexed(k: int, edges: Sequence[tuple[int, int, int]]) -> tuple:
    lab = {n: "0" for n in range(k)}
    for _ in range(k):
        new = {}
        for n in range(k):
            sig = []
            for u, v, t in edges:
                if u == v == n:
                    sig.append(("self", t))
                elif u == n:
                    sig.append(("out", t, lab[v]))
                elif v == n:
                    sig.append(("in", t, lab[u]))
            new[n] = hashlib.blake2b((lab[n] + repr(sorted(sig))).encode(),
                                     digest_size=6).hexdigest()
        if new == lab:
            break
        lab = new
    return (tuple(sorted(lab.values())),
            tuple(sorted((lab[u], lab[v], t) for u, v, t in edges)))


def core_class(k: int, e: int, n_types: int, self_loops: bool
               ) -> tuple[int, dict[tuple, int]]:
    """Alle zusammenhängenden Kerne auf k Knoten mit e Kanten.

    Gibt (gesamt_beschriftet, form -> Zahl beschrifteter Realisierungen).

    Exakt abgezählt, gemessen (2 Typen, Selbstschleifen erlaubt):
        k=4 e=3 ->   1.024 Kerne,    52 Formen
        k=4 e=4 ->  16.640 Kerne,   751 Formen
        k=5 e=4 ->  32.000 Kerne,   331 Formen
        k=5 e=5 -> 739.328 Kerne, 6.742 Formen

    Nebenbefund: von (4,4) zu (5,4) verdoppelt sich die Kernzahl, aber die
    Formenzahl SINKT (751 -> 331). Bei mehr Knoten und gleichen Kanten sind
    Formen dünner verteilt und häufiger. Das ist die Größenabhängigkeit als
    echte Abzählung — nicht als geratener Exponent.

    WARNUNG: kombinatorisch. Die Slotzahl ist k*k*n_types (bzw. ohne
    Selbstschleifen k*(k-1)*n_types), und es wird über alle e-Teilmengen
    iteriert. Ab etwa k=6, e=6 unbrauchbar.
    """
    S = _slots(k, n_types, self_loops)
    total = 0
    per: dict[tuple, int] = defaultdict(int)
    for c in combinations(S, e):
        if not _connected(k, c):
            continue
        total += 1
        per[_canon_indexed(k, c)] += 1
    return total, dict(per)


def pendant_factor(k: int, j: int, n_types: int) -> float:
    """j angehängte Knoten, je genau EINE Kante an einen KERNknoten.

    Pro Anhang: k Kernknoten x 2 Richtungen x n_types. Geteilt durch j!, weil
    Knoten nur durch ihre Struktur definiert und damit ununterscheidbar sind.
    """
    return (k * 2 * n_types) ** j / factorial(j)


def reference_class_size(k: int, e: int, j: int, n_types: int,
                         self_loops: bool) -> float:
    """Größe der Bezugsklasse: Kernzahl x Anhangvarianten."""
    total, _ = core_class(k, e, n_types, self_loops)
    return total * pendant_factor(k, j, n_types)


def structure_probability(g: PerspectiveGraph, sub: NodeSet) -> float:
    """Wahrscheinlichkeit dieser Struktur in ihrer Bezugsklasse.

    Selbstschleifen und Kantentypen werden AUS DEM MEDIUM abgeleitet (g), nicht
    gesetzt. j = Zahl der Randkanten der Struktur.

    Gemessen k=5, e=4, j=3: Bezugsklasse 42.666.667, P = 2,81e-6.

    Beschriftet oder formbasiert ist rechnerisch fast gleichgültig — 2,81e-6
    gegen 2,27e-6, nur 24% Unterschied, obwohl die Bezugsklassen um Faktor 97
    auseinanderliegen. Der Zähler wächst mit dem Nenner.

    VORBEHALT: ohne zu wissen, wie das Medium erzeugt wird, ist die Aussagekraft
    dieser Zahl geschätzt, nicht bewiesen. Es ist ein Messwert, keine Wahrheit.
    """
    k = len(sub)
    e = n_inner(g, sub)
    j = len(crossings(g, sub))
    n_types = max(1, len(edge_types_in(g)))
    sl = medium_has_self_loops(g)

    total, per = core_class(k, e, n_types, sl)
    if total == 0:
        return 0.0
    mine = per.get(_canon_of_sub(g, sub, n_types), None)
    if mine is None:
        # Form nicht in der Bezugsklasse gefunden -> haeufigste als Obergrenze
        # meldet ehrlich, dass die Zuordnung nicht gelang
        return float("nan")
    return mine / (total * pendant_factor(k, j, n_types))


def _canon_of_sub(g: PerspectiveGraph, sub: NodeSet, n_types: int) -> tuple:
    """Struktur auf Indexform bringen, damit sie mit core_class vergleichbar ist."""
    order = {n: i for i, n in enumerate(sorted(sub, key=lambda x: str(x)))}
    type_order = {t: i for i, t in enumerate(edge_types_in(g))}
    edges = [(order[e.source], order[e.target], type_order[e.edge_type])
             for e in inner_edges(g, sub)]
    return _canon_indexed(len(sub), edges)


# =============================================================================
# NICHT GEBAUT — Markierungen AM ORT, wo die Methoden liegen würden
# =============================================================================
# Pflicht laut meta.workflow: eine unmarkierte Lücke liest sich als
# absichtlich-abwesend, und eine spätere Sitzung diagnostiziert sie neu als
# Befund, statt sie als bekannte Arbeit zu erben.

def score(*_args, **_kwargs):
    """DESIGNED, NOT BUILT: KB: KEIN KNOTEN — offener Punkt bisher nur in
    ga_gesamtdesign.md §16.6 festgehalten, braucht einen eigenen Knoten.
    (Die Vorgabe meta.handoff verlangt hier eine Knoten-Id; dass keine
    existiert, ist der Mangel — nicht durch eine erfundene Id verdecken.)

    Sollte Deckung, Größe und Zonengröße einer Correlation zu EINER Ordnung
    verrechnen. NICHT gebaut, weil die Verrechnung nie festgelegt wurde. Eine
    frühere Fassung multiplizierte sie samt Anreicherung — das war Erfindung,
    keine Entscheidung, und vermischte außerdem die zwei getrennten
    Wahrscheinlichkeitsfragen (Zwischenbuchhaltung gegen Endauswertung).

    Correlation liefert die drei Zahlen bewusst einzeln. Wer ordnen will,
    ordnet selbst, bis Sven die Verrechnung festlegt.
    """
    raise NotImplementedError("Verrechnung der Paarungsgewichte nicht festgelegt")


def sharpness(*_args, **_kwargs):
    """DESIGNED, NOT BUILT: KB: KEIN KNOTEN — offener Punkt bisher nur in
    ga_gesamtdesign.md §16.11 festgehalten, braucht einen eigenen Knoten.

    Größe als Schärfefaktor — "mehr Knoten heißt mehr mögliche Graphen, also ist
    eine größere wiederkehrende Struktur ein schärferes Signal". Eine frühere
    Fassung schrieb `größe ** gewicht`; das ist keine Abzählung des
    Möglichkeitsraums, sondern ein geratener Exponent.

    Die echte Grundlage liegt inzwischen vor: core_class() zählt exakt, wie viele
    Formen es je (k, e) gibt. Gemessen sinkt die Formenzahl von (4,4) zu (5,4)
    sogar (751 -> 331). Der Schärfefaktor ist daraus ableitbar — aber die
    Ableitung ist nicht entworfen.

    FEHLT AUSSERDEM: Automorphismen. form() liefert sie nicht, und ohne sie ist
    die analytische Zählung unvollständig.
    """
    raise NotImplementedError("Schärfefaktor nicht aus dem Möglichkeitsraum abgeleitet")


def detect_pattern(*_args, **_kwargs):
    """DESIGNED, NOT BUILT: KB: perspective.baby_ga_single_run (Schlüssel
    fitness_input und negativity_required). Ausführlich ga_gesamtdesign.md §4.

    Mustererkennung über einer Ebenenmenge, mit Positiv- UND Negativseite: das
    Muster muss da sein wo es soll UND fehlen wo es nicht soll. Auslöser und
    Mustererkennung sind dasselbe; einziger variabler Teil ist die Herkunft des
    Musters (bekannt oder statistisch identifiziert).

    Trennschärfe MUSS als DIFFERENZ gerechnet werden (Trefferquote minus
    Fehlalarmquote), nicht als Produkt. Beim Produkt bekam eine Form, die die
    Eingaben quer zum Label spaltet, 0,25, wo identische Positiv- und
    Negativmengen 0 ergeben müssen.

    NICHT gebaut, weil die Fitness-Schnittstelle fehlt (§7) — ohne sie gibt es
    keine definierte Positiv-/Negativmenge. Baustein vorhanden: form_entropy()
    liefert das Negativsignal für Arithmetik (chaotischer Graph).
    """
    raise NotImplementedError("braucht die Fitness-Schnittstelle, §7")


# NOT ON SOLVE PATH: das gesamte Modul. Zum Verdrahten fehlt der GA-Lauf (§3)
# und die steckbare Fitness-Schnittstelle (§7). Siehe Modul-Docstring.
