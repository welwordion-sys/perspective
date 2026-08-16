"""
ga.py — Prototyp 2, Stufe 1a. Der GA selbst.

Baut §3 bis §10 aus ga_gesamtdesign.md. Ein Stück, keine Module auf Vorrat:
die Fitness ist ohne Eingabenpopulation nicht definiert, die Population ist
ohne Ebenenabfolge sinnlos, und die Ebenenabfolge IST der Travelpath. Wer das
zerlegt, baut Schnittstellen gegen Bedeutungen, die es einzeln nicht gibt.

WAS HIER NICHT DRIN IST, UND WARUM
  - Kein Lesen des Aufzeichnungsgraphen. §2, Stufe 1: das Archiv wird
    geschrieben und NIE gelesen, absichtlich. Der fehlende Lesekanal ist keine
    Lücke und darf nicht "repariert" werden.
  - Keine Abbildungssynthese. §9: Rekombination erbt die operationale Abbildung
    nicht, sie müsste durch Mutation gebaut werden — und dieser Knoten ist
    derselbe wie rule_collapse_self_similarity und gehört ausdrücklich in den
    späteren graphbasierten Übergang, nicht in die Babyphase. Die betroffenen
    Actions stehen unten als NotInBabyPhase, nicht als Stub, der so tut.
  - Kein Eingriff in basic_machinery. §10: der GA fasst den rohen Graphen nie
    an; er handelt ausschließlich über die vorhandenen Operatoren.

VERHÄLTNIS ZU travel_loop.fire_layer
  fire_layer ruft reclassify_after_firing, und die schreibt SIDEWAYS sofort aus
  der Evidenz EINER Eingabe — wobei LayerRecord.__post_init__ das Löschen der
  Provenienz erzwingt. Für den GA ist das falsch (§6): Reversibilität ist eine
  Eigenschaft der REGELGRUPPE über der EINGABENPOPULATION, nicht einer Feuerung.
  Deshalb ruft der GA fire_layer nicht auf, sondern feuert und urteilt getrennt:
  sammeln während des Laufs, setzen erst danach. fire_layer bleibt für
  Nicht-GA-Nutzung unangetastet.
"""
from __future__ import annotations

import math
import os
import random
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

_R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in ['', 'grouping', 'builders', 'basic_machinery']:
    _q = os.path.join(_R, _p)
    if _q not in sys.path:
        sys.path.insert(0, _q)

from basic_machinery.graph import PerspectiveGraph, Node, EdgeType
from basic_machinery.layers import (LayeredGraph, LayerRegistry, LayerRecord,
                                    TravelType)
from basic_machinery.schema import apply_compound
from basic_machinery.reverse_compound import reverse_fire
from grouping.matcher import Matcher


# ===========================================================================
# §4  Das Fitnesskriterium — steckbar, hinter fester Schnittstelle
# ===========================================================================

@dataclass(frozen=True)
class Signal:
    """Das Outcome einer Kriteriumsauswertung über einer Ebenenmenge.

    §4: BEIDE SEITEN SIND PFLICHT. Nur Anwesenheit zu messen ist wertlos — ein
    Muster, das überall auftaucht, unterscheidet nichts.

    §4 (gemessen): Trennschärfe ist eine DIFFERENZ, kein Produkt. Beim Produkt
    bekam eine Form, die die Eingaben quer zum Label spaltet, einen guten Wert;
    bei identischen Positiv- und Negativmengen kam 0,25 heraus statt 0.
    """
    hit_rate: float        # Anteil der Positiven, in denen das Muster liegt
    false_alarm_rate: float      # Anteil der Negativen, in denen es auch liegt
    n_positive: int
    n_negative: int

    @property
    def separation(self) -> float:
        return self.hit_rate - self.false_alarm_rate

    def __str__(self) -> str:
        return (f"Treffer {self.hit_rate:.2f} - Fehlalarm "
                f"{self.false_alarm_rate:.2f} = {self.separation:+.2f}")


class Criterion:
    """Steckbare Schnittstelle. §1: woran 'Outcome' gemessen wird, sagt der GA
    NICHT selbst — das sagt das Criterion. Der GA ist gegenüber der Domäne
    gleichgültig; die Allgemeinheit trägt das Criterion, nicht ein Eingriff in
    den GA.

    §4: Auslöser und Mustererkennung sind DASSELBE. Ein Zustand ist prüfreif,
    wenn das Muster vorliegt; es braucht keine zweite, andersartige Bedingung.
    Deshalb hat diese Schnittstelle genau eine Methode und keinen getrennten
    Auslöser.
    """

    name = "unbenannt"

    def holds(self, g: PerspectiveGraph) -> bool:
        """Liegt das Muster in diesem Zustand vor?"""
        raise NotImplementedError

    def evaluate(self, positive: Sequence[PerspectiveGraph],
                negative: Sequence[PerspectiveGraph]) -> Signal:
        """Über einer Menge von Zuständen. §3: der Messpunkt ist ebenenlokal,
        die Bedeutung pfadweit."""
        if not positive:
            return Signal(0.0, 0.0, 0, len(negative))
        tq = sum(1 for g in positive if self.holds(g)) / len(positive)
        fq = (sum(1 for g in negative if self.holds(g)) / len(negative)
              if negative else 0.0)
        return Signal(tq, fq, len(positive), len(negative))


class KnownPattern(Criterion):
    """Arithmetik. §4: 'Der einzige variable Teil ist die Herkunft des Musters:
    bekannt oder statistisch identifiziert. Bei Arithmetik ist es bekannt.'

    Das Muster wird als Prädikat über dem Graphen hereingereicht — §4: 'Das
    Criterion selbst wird individuell vom Nutzer aus bereitgestellten
    Informationen für ein Problem zusammengesetzt.' Der GA baut es nicht.
    """

    def __init__(self, name: str, pattern: Callable[[PerspectiveGraph], bool]):
        self.name = name
        self._pattern = pattern

    def holds(self, g: PerspectiveGraph) -> bool:
        return bool(self._pattern(g))


# ===========================================================================
# §6  Regellegalität und Reversibilität — über der POPULATION, nicht je Feuerung
# ===========================================================================

@dataclass
class VerdictLedger:
    """Sammelt reverse_fire-Urteile je (Regelgruppe, Eingabe), OHNE zu setzen.

    §6, der bestätigte Fehler: reclassify_after_firing prüft an genau einem
    Graphenpaar und setzt bei True sofort SIDEWAYS — was das Löschen der
    Provenienz ERZWINGT (LayerRecord.__post_init__ weist SIDEWAYS mit
    Provenienz zurück). Eine Gruppe kann auf Eingabe A umkehrbar und auf B
    verlustbehaftet sein; ist sie an A geprüft worden, ist die Umkehrung für B
    auf keinem Weg mehr erreichbar. Nicht wiederherstellbar.

    §6, was gelten muss: SIDEWAYS erst, wenn die Umkehrung für ALLE Eingaben
    bewiesen ist. Ein einziges 'unverifiable' blockiert — genauso, wie die
    strikte Identitätsprüfung `is True` es heute schon innerhalb einer Eingabe
    tut.

    Sven, diese Sitzung: das Löschen bringt ohnehin nichts, gebraucht wird nur
    ein Flag. Also wird während des Laufs gar nicht umgeschrieben; die
    Provenienz bleibt stehen und ist noch da, falls ein spätes Gegenbeispiel
    kommt.
    """
    verdicts: dict[tuple, dict[int, object]] = field(default_factory=lambda: defaultdict(dict))

    def record(self, group: tuple, input_id: int, verdict: object) -> None:
        self.verdicts[group][input_id] = verdict

    def is_reversible(self, group: tuple, expected_inputs: int) -> bool:
        """Poisoned-Apple eine Stufe höher als layers.py: EINE Ausnahme kippt
        die ganze Gruppe. Auch eine fehlende Eingabe kippt sie — ungeprüft ist
        nicht bewiesen."""
        per_input = self.verdicts.get(group, {})
        if len(per_input) < expected_inputs:
            return False
        return all(v is True for v in per_input.values())

    def reason(self, group: tuple, expected_inputs: int) -> str:
        je = self.verdicts.get(group, {})
        if len(je) < expected_inputs:
            return f"nur {len(je)}/{expected_inputs} Eingaben geprüft"
        bad = {k: v for k, v in je.items() if v is not True}
        if not bad:
            return f"alle {expected_inputs} Eingaben umkehrbar"
        kinds = sorted({str(v) for v in bad.values()})
        return f"{len(bad)}/{expected_inputs} Eingaben: {', '.join(kinds)}"


def commit_reversibility(ledger: VerdictLedger, runs: list["InputRun"],
                          expected_inputs: int) -> dict[tuple, bool]:
    """DER NACHGELAGERTE DURCHGANG. Erst hier wird geschrieben.

    §6: 'Die Provenienz darf erst fallen, wenn das für die ganze Population
    steht.' Vorher steht sie, weil ein Zurücknehmen sonst unmöglich wäre —
    genau das Argument, das §6 gegen vorläufiges Setzen anführt.
    """
    flags: dict[tuple, bool] = {}
    for group in ledger.verdicts:
        flags[group] = ledger.is_reversible(group, expected_inputs)

    for run in runs:
        for key, group in run.layer_to_group.items():
            if not flags.get(group, False):
                continue                      # bleibt UPWARD, Provenienz bleibt
            old = run.registry.get(key)
            if old is None or old.travel_type is TravelType.SIDEWAYS:
                continue
            run.registry.reclassify(key, LayerRecord(
                key=key, travel_type=TravelType.SIDEWAYS,
                ruleset=old.ruleset, provenance=None, parents=old.parents))
    return flags


# ===========================================================================
# §3  Der einzelne Run — eine Regelgruppe je Ebene, über der Population
# ===========================================================================

@dataclass
class LayerStep:
    """Was an EINER Eingabe auf EINER Ebene passiert ist."""
    key: object
    fired: bool
    verdict: object = None
    state: PerspectiveGraph | None = None


@dataclass
class InputRun:
    """Der Zustand einer einzelnen Eingabe während eines Travelpath-Laufs."""
    input_id: int
    lg: LayeredGraph
    registry: LayerRegistry
    current: object
    steps: list[LayerStep] = field(default_factory=list)
    layer_to_group: dict = field(default_factory=dict)
    stuck: bool = False

    def state(self) -> PerspectiveGraph:
        return self.lg.materialize(self.current)


class MoveWorks:
    """§10 Mutationsstabilität: der GA fasst den rohen Graphen NIE an.
    Kontrollierte Operatoren tun das. Freiheit heißt: volle Freiheit INNERHALB
    eines wohlgeformten Graphen, keine außerhalb. Das hier ist die einzige
    Stelle, an der der GA das Substrat berührt.
    """

    def __init__(self, matcher_build: Callable[[Sequence[str]], Matcher] | None = None):
        self._cache: dict[tuple, Matcher] = {}
        self._bau = matcher_build or (lambda namen: Matcher(list(namen)))

    def matcher(self, group: tuple) -> Matcher:
        if group not in self._cache:
            self._cache[group] = self._bau(group)
        return self._cache[group]

    def move(self, run: InputRun, group: tuple, new_key
              ) -> LayerStep:
        """EIN Zug an EINER Eingabe. Feuern und Urteilen sind hier GETRENNT —
        das ist der Unterschied zu travel_loop.fire_layer, siehe Kopf."""
        base = run.lg.materialize(run.current)
        matches = self.matcher(group).collect_all(base)
        if not matches:
            # §5: 'lokal unverändert heißt nur, dass keine vorhandene Regel
            # damit interagiert.' Kein Signal, kein Schritt.
            return LayerStep(new_key, fired=False)

        apply_compound(run.lg, run.registry, run.current, new_key,
                       matches)
        result = run.lg.materialize(new_key)

        # Urteil holen, aber NICHT setzen. §6.
        try:
            verdict = reverse_fire(matches, base, result).get("reversible")
        except Exception as e:                      # noqa: BLE001
            verdict = f"fehler:{type(e).__name__}"

        return LayerStep(new_key, fired=True, verdict=verdict,
                             state=result)


# ---------------------------------------------------------------------------
# §5  Loops
# ---------------------------------------------------------------------------

@dataclass
class PathPart:
    """Ein Baustein des Travelpaths. Entweder eine gewöhnliche Ebene oder ein
    Loop.

    §3: 'Für die Tiefenberechnung zählt ein Loop als EIN Baustein', nicht als
    so viele Ebenen wie Wiederholungen — sonst erschiene derselbe Algorithmus
    je nach Eingabegröße verschieden tief. Das gilt auch für die Entfernung,
    mit der der Fruchtbarkeitsbonus abfällt: der Loop ist EINEN Schritt weit,
    nicht n.

    §3: 'Fester Wiederholungszähler ist KEIN Loop.' Ein fester Zähler ist eine
    ausgerollte Folge und wird wie gewöhnliche Ebenen behandelt — mit
    Fruchtbarkeit an jeder Stelle und voller Tiefenzählung. Deshalb trägt ein
    PathPart `is_loop` und nicht bloß eine Wiederholungszahl.
    """
    group: tuple
    is_loop: bool = False
    turns: dict[int, int] = field(default_factory=dict)  # je Eingabe

    @property
    def depth(self) -> int:
        return 1        # auch der Loop. §3.

    def sprout_points(self) -> tuple[str, ...]:
        """§3: 'Die Mitte eines Loops ist kein Ort für Fruchtbarkeit' — dort zu
        sprießen hieße, in einen Block hineinzuwachsen, dessen
        Wiederholungszahl gar nicht festliegt; die Einfügung hätte keine
        bestimmte Stelle. 'Ein Loop kann nur am Ende sprießen.'"""
        return ("after",) if self.is_loop else ("at",)


def loop_detected(group: tuple, steps_per_input: list[list[LayerStep]]
                 ) -> bool:
    """§5, IN DIESER REIHENFOLGE: gleiche Regelgruppe -> mindestens EINE Ebene
    hat erfolgreich fired -> DANACH globale Stabilität. Nicht gleichzeitig;
    das erfolgreiche Feuern geht der Stabilität voraus.

    steps_per_input: je Eingabe die Schrittfolge unter DERSELBEN Gruppe.
    """
    if not steps_per_input:
        return False
    has_fired = any(s.fired for seq in steps_per_input for s in seq)
    if not has_fired:
        return False
    # Globale Stabilität DANACH: jede Eingabe endet damit, dass nichts mehr
    # matcht. Ein fester Zähler erfüllt das nicht — dort geht es mit anderen
    # Regeln weiter, bevor Stabilität eintritt. (§3 offen: ob das als
    # Unterscheidung reicht, ist ungeprüft — hier so umgesetzt, nicht bewiesen.)
    return all(seq and not seq[-1].fired for seq in steps_per_input)


# ---------------------------------------------------------------------------
# §3  Kredit und Fruchtbarkeit — ZWEI Größen
# ---------------------------------------------------------------------------

@dataclass
class Attention:
    """Sven, diese Sitzung — Korrektur an §3, das sie als EINE Größe führt:

        'Kredit ist der Vermerk über Erfolg. Fruchtbarkeit die Grösse des
        Aufmerksamkeitsbonus den wir geben pro Kredit.'

    Also zwei Größen: Kredit ist die gespeicherte Bewertung, Fruchtbarkeit die
    daraus abgeleitete Erzeugungsrate. §3 führte genau diese Trennung als
    '(zu klären)' — hiermit geklärt.

    Richtung, §3: 'ein guter Fitnesstest macht die getestete Ebene (auf) und
    den Unterbau darunter (unterhalb) fruchtbarer — nicht oberhalb — und der
    Bonus fällt mit der Entfernung zum Test.' Oberhalb ist noch nichts gebaut
    und nichts bewertet, dort wäre jede Zuweisung spekulativ. Kurz: Kredit nur
    für Erreichtes und Geprüftes, nie für Erhofftes.

    Abfall: Sven schlug `4/5, 4/6, 4/7, 4/8 ...` vor, mit einem ausdrücklichen
    Fragezeichen. Das ist c/(c+d). c ist PARAMETER, keine eingebaute Konstante —
    ungemessen, und ein Run soll ihn beantworten können, nicht der Schreibtisch.
    """
    c: float = 4.0
    credit: dict[int, float] = field(default_factory=lambda: defaultdict(float))

    def award(self, test_index: int, parts: Sequence[PathPart],
                 separation: float) -> None:
        """Kredit wird AM TESTPUNKT vermerkt; die Fruchtbarkeit ist die daraus
        abgeleitete Wirkung (siehe fertility())."""
        self.credit[test_index] += separation

    def fertility(self, index: int, parts: Sequence[PathPart]) -> float:
        """Bonus an Stelle `index`, summiert über alle Kredite.

        Entfernung wird in BAUTEILEN gezählt, nicht in Ebenen — ein Loop ist
        einen Schritt weit, nicht n (§3). Oberhalb des Tests: null.
        """
        # §3: 'Die Mitte eines Loops ist kein Ort fuer Fruchtbarkeit ... ein
        # Loop kann nur am Ende spriessen.' sprout_points sagt, ob diese Stelle
        # ueberhaupt sprossfaehig ist. Vorher war die Methode definiert und
        # NIRGENDS aufgerufen — die Regel stand da, wirkte aber nicht.
        if index < len(parts) and not parts[index].sprout_points():
            return 0.0
        bonus = 0.0
        for test_index, value in self.credit.items():
            if index > test_index:
                continue                         # oberhalb: nichts. §3.
            d = sum(b.depth for b in parts[index:test_index])
            bonus += value * (self.c / (self.c + d))
        return bonus


# ---------------------------------------------------------------------------
# §8  Erzeugung — Actions getrennt von Strategies
# ---------------------------------------------------------------------------

class NotInBabyPhase(NotImplementedError):
    """§9: Rekombination erbt die operationale Abbildung NICHT; sie müsste
    durch Mutation gebaut werden, bis sie gültig ist. Dieses
    Abbildungs-Syntheseproblem ist derselbe Knoten wie
    rule_collapse_self_similarity und gehört zum SPÄTEREN graphbasierten
    Übergang. §9 wörtlich: 'Er wird hier bewusst umgangen.'

    Diese Actions stehen deshalb als benannte Leerstelle da und nicht als Stub,
    der so tut, als könnte er es.
    """


class Actions:
    """§8. AKTIONEN, nicht Strategies — die Trennung ist der Punkt des
    Abschnitts; eine frühere Liste vermischte beides.

    An Regelgruppen (in Stufe 1a voll gebaut, weil sie ohne Abbildungssynthese
    auskommen): merge, split, wiederholen.

    An Regeln: recombine, Delta-Gruppen recombine, reversible Regel
    umkehren, am Kern im DAG mutieren, fresh erzeugen. Diese brauchen alle
    entweder eine neue Abbildung oder eigene Platzhalter — siehe
    NotInBabyPhase.
    """

    def __init__(self, supply: Sequence[str], rng: random.Random):
        self.supply = list(supply)
        self.rng = rng

    # --- an Regelgruppen -------------------------------------------------
    def merge(self, a: tuple, b: tuple) -> tuple:
        return tuple(sorted(set(a) | set(b)))

    def split(self, g: tuple) -> tuple[tuple, tuple]:
        if len(g) < 2:
            return g, ()
        cut = self.rng.randrange(1, len(g))
        shuffled = list(g)
        self.rng.shuffle(shuffled)
        return tuple(sorted(shuffled[:cut])), tuple(sorted(shuffled[cut:]))

    def wiederholen(self, g: tuple) -> tuple:
        """Als Aktion ist das gestrichen — siehe Strategies.escalate."""
        raise NotImplementedError(
            "Sven, diese Sitzung: Wiederholung als AKTION ist Unsinn, sie "
            "entsteht im Loop von selbst. Als STRATEGIE heisst es 'konservativ "
            "bleiben mit Mutation und Rekombination, bis du nicht mehr "
            "weiterkommst' — das steht in Strategies.escalate.")

    def grow(self, g: tuple, n: int = 1) -> tuple:
        frei = [r for r in self.supply if r not in set(g)]
        if not frei:
            return g
        return tuple(sorted(set(g) | set(self.rng.sample(frei, min(n, len(frei))))))

    def shrink(self, g: tuple, n: int = 1) -> tuple:
        if len(g) <= 1:
            return g
        drop = set(self.rng.sample(list(g), min(n, len(g) - 1)))
        return tuple(sorted(set(g) - drop))

    def fresh(self, size: int = 4) -> tuple:
        k = min(size, len(self.supply))
        return tuple(sorted(self.rng.sample(self.supply, k)))

    # --- an Regeln -------------------------------------------------------
    def recombine(self, a: str, b: str):
        raise NotInBabyPhase(
            "Eingabemuster von A, Ausgabemuster von B — die Abbildung dazwischen "
            "wird nicht geerbt und müsste synthetisiert werden (§9).")

    def reverse_rule(self, r: str):
        raise NotInBabyPhase(
            "Umkehren braucht eigene Platzhalter, weil sich ändert, welche Seite "
            "gematcht wird (§8).")

    def mutate_core(self, r: str):
        raise NotInBabyPhase(
            "Gruppenmutation am Kern im DAG (§8/§9) — der DAG liefert die "
            "Gruppenstruktur, die Abbildung nicht.")


class Strategies:
    """§8. Strategies sagen, WIE stark gegriffen wird; die Fruchtbarkeit sagt,
    WO überhaupt gehandelt wird.

    §8 (offen): Mischung und Gewichtung sind auf dem Arithmetiktest NICHT
    messbar — die Regeln sind dort schon korrekt, Wiederverwendung ist trivial
    optimal, der Test kann Strategies nicht unterscheiden. Echter Test ist
    Stufe 1b. Die Gewichte hier sind darum gleichverteilt und ausdrücklich
    nicht gemessen.

    §8 (verworfen): Achsen-Variation entlang bekannter Achsen wie Bitwert,
    Übertrag, Breiten — sie setzt Struktur voraus, die der GA nicht kennen darf.
    Ist hier deshalb nicht vorhanden.
    """

    def __init__(self, actions: Actions, rng: random.Random):
        self.a = actions
        self.rng = rng

    def nudge(self, g: tuple) -> tuple:
        return self.a.grow(g, 1) if self.rng.random() < 0.5 else self.a.shrink(g, 1)

    def shake(self, g: tuple) -> tuple:
        return self.a.grow(g, 3) if self.rng.random() < 0.5 else self.a.shrink(g, 3)

    def prefer_reversible(self, g: tuple, flags: dict[tuple, bool]) -> tuple:
        known_good = [k for k, v in flags.items() if v]
        if not known_good:
            return self.nudge(g)
        return self.a.merge(g, self.rng.choice(known_good))

    def split_off(self, g: tuple) -> tuple:
        """Actions.split war gebaut und in KEINE Strategie verdrahtet. §8 fuehrt
        Aufspalten als Gruppenaktion; hier nimmt die Strategie eine Haelfte."""
        a, b = self.a.split(g)
        return a if (b == () or self.rng.random() < 0.5) else b

    def sideways_hunt(self, g: tuple) -> tuple:
        """§8: 'Sideways-Jagd unter dünner Regelmenge.' Dünn heißt dünn."""
        return self.a.shrink(g, max(1, len(g) // 2))

    def cold_start(self) -> tuple:
        return self.a.fresh()

    def escalate(self, stall: int) -> tuple[float, float, float, float, float]:
        """Sven, diese Sitzung, zur gestrichenen Aktion 'wiederholen':

            'bleibe konservativ mit Mutation und Rekombination bis du nicht
             mehr weiterkommst'

        Konservativ heisst: solange Fortschritt da ist, kleine Schritte. Erst
        beim Steckenbleiben wird grob gegriffen. `stall` = Generationen ohne
        Verbesserung. Vorher waren die Gewichte fest (30/20/20/20/10) und
        griffen bei Fortschritt genauso grob wie im Stillstand.

        Rueckgabe: (nudge, shake, prefer_reversible, sideways_hunt, cold_start).
        Der Uebergang ist stetig, damit es keine Schwelle gibt, an der das
        Verhalten springt; e ist der Eskalationsgrad in [0,1).
        """
        e = 1.0 - self.a.rng.random() * 0 - (1.0 / (1.0 + stall))  # 0 bei stall=0
        cons = 1.0 - e
        return (0.55 * cons + 0.05,      # nudge: dominiert, solange es laeuft
                0.10 + 0.30 * e,          # shake
                0.15,                     # prefer_reversible: lageunabhaengig
                0.10 + 0.20 * e,          # sideways_hunt
                0.05 + 0.25 * e)          # cold_start: nur im Stillstand ernst

    def candidates(self, base: tuple, flags: dict[tuple, bool], n: int = 6,
                   stall: int = 0) -> list[tuple]:
        """Mehrere Strategies speisen EINEN gemeinsamen Kandidatenpool
        (ga_generator_policy). Keine Strategie hat einen eigenen Pool."""
        w = self.escalate(stall)
        kum, s = [], 0.0
        for x in w:
            s += x; kum.append(s)
        pool = []
        for _ in range(n):
            r = self.rng.random() * s
            if r < kum[0]:   pool.append(self.nudge(base))
            elif r < kum[1]: pool.append(self.shake(base))
            elif r < kum[2]: pool.append(self.prefer_reversible(base, flags))
            elif r < kum[3]: pool.append(self.sideways_hunt(base)
                                         if self.rng.random() < 0.5
                                         else self.split_off(base))
            else:            pool.append(self.cold_start())
        seen, out = set(), []
        for k in pool:
            if k and k not in seen:
                seen.add(k); out.append(k)
        return out


# ===========================================================================
# §3  Der Run
# ===========================================================================

@dataclass
class Travelpath:
    """§1: geordnete Folge von Regelschichten, die von einer Eingabe zu einem
    Outcome führt. Ein Travelpath IST ein Algorithmus.

    Sven, diese Sitzung: 'deshalb muss jeder Teil, jede Ebene an multiplen
    Inputs getestet werden.'
    """
    parts: list[PathPart] = field(default_factory=list)
    signals: list[Signal] = field(default_factory=list)

    @property
    def depth(self) -> int:
        return sum(b.depth for b in self.parts)

    def quality(self, credit: dict[int, float] | None = None) -> float:
        """§3: 'Der Messpunkt ist ebenenlokal, die Bedeutung pfadweit. Die
        Ebene ist der Messpunkt, der Pfad das Bewertete.' (Zeile 105-108.)

        WIE mehrere Messpunkte zusammengefasst werden, sagt §3 nicht. Sven,
        diese Sitzung, entscheidet es:

            'wenn mehrere Ebenen in einem Pfad Kredit haben, wie fasst man die
             Wahrscheinlichkeiten zusammen. Ich würde jeder Ebene ein Gewicht
             geben, ein Standardwert von 1 durch Ebenenanzahl + Kreditsumme.'

        Also w_i = 1/n + credit_i, dann gewichtetes Mittel. Ohne Kredit ist
        das Mittel ungewichtet — jede Ebene zählt 1/n. Mit Kredit wandert das
        Gewicht auf die Ebenen, die sich bewährt haben.

        Vorher stand hier min() über alle Signale. Das war MEINE Erfindung und
        stand nirgends im Design; sie ist ersetzt, nicht ergänzt.
        """
        if not self.signals:
            return 0.0
        n = len(self.signals)
        credit = credit or {}
        weights = [1.0 / n + max(0.0, credit.get(i, 0.0)) for i in range(n)]
        total = sum(weights)
        if total <= 0:
            return sum(s.separation for s in self.signals) / n
        return sum(w * s.separation for w, s in zip(weights, self.signals)) / total


class Run:
    """§3: 'Das war die Lücke, die alle früheren Knoten offen ließen: sie
    beschrieben die Evolution des GA, nie den EINZELNEN Run.'"""

    def __init__(self, inputs: Sequence[PerspectiveGraph], criterion: Criterion,
                 moveworks: MoveWorks, seed_layer: Callable, max_parts: int = 12,
                 max_loop_turns: int = 40):
        self.inputs = list(inputs)
        self.criterion = criterion
        self.moveworks = moveworks
        self.seed_layer = seed_layer
        self.max_parts = max_parts
        self.max_loop_turns = max_loop_turns
        self.ledger = VerdictLedger()

    def _fresh_runs(self) -> list[InputRun]:
        runs = []
        for i, g in enumerate(self.inputs):
            lg, reg = LayeredGraph(), LayerRegistry()
            self.seed_layer(lg, g, 0)
            runs.append(InputRun(i, lg, reg, 0))
        return runs

    def walk(self, plan: Sequence[tuple]) -> tuple[Travelpath, list[InputRun]]:
        """Führt EINEN Bauplan (Folge von Regelgruppen) über der GANZEN
        Population aus.

        §3: 'Alle Eingaben teilen dieselbe Regelgruppe pro Ebene — sonst würde
        man nicht den Travelpath testen, sondern pro Eingabe etwas anderes, und
        dann wäre es kein Algorithmus.'

        §3: 'Die EINZIGE Freiheit zwischen Eingaben ist die Looplänge.' Davor
        stehen alle auf derselben Ebene, im Loop drehen sie unterschiedlich oft,
        danach sind sie wieder synchron. Deshalb hängt die Abbruchbedingung
        eines Loops pro Eingabe an der Stabilisierung und ist NICHT global.
        """
        runs = self._fresh_runs()
        path = Travelpath()
        next_key = {l.input_id: 1 for l in runs}

        for group in plan[:self.max_parts]:
            per_input_steps: list[list[LayerStep]] = []
            turns: dict[int, int] = {}

            for run in runs:
                seq: list[LayerStep] = []
                for _ in range(self.max_loop_turns):
                    key = next_key[run.input_id]
                    schritt = self.moveworks.move(run, group, key)
                    seq.append(schritt)
                    if not schritt.fired:
                        break
                    next_key[run.input_id] = key + 1
                    run.current = key
                    run.layer_to_group[key] = group
                    run.steps.append(schritt)
                    self.ledger.record(group, run.input_id, schritt.verdict)
                turns[run.input_id] = sum(1 for s in seq if s.fired)
                per_input_steps.append(seq)

            if not any(w for w in turns.values()):
                break                       # nichts hat gegriffen: Pfad endet

            is_loop = (loop_detected(group, per_input_steps)
                        and len(set(turns.values())) > 1)
            part = PathPart(group, is_loop=is_loop, turns=turns)
            path.parts.append(part)

            # §3: der Messpunkt ist ebenenlokal. §3 zu Loops: 'Der Fitnesstest
            # gehört normalerweise ans ENDE des Loops — gelegentlich auch an den
            # Anfang. Nicht dazwischen.' Nach der Schleife oben stehen alle
            # Eingaben am Loopende, also wird genau dort gemessen.
            path.signals.append(self._measure(runs))

        return path, runs

    def _measure(self, runs: list[InputRun]) -> Signal:
        """§4: BEIDE SEITEN. Positiv = die Zustände, die das Criterion erfüllen
        SOLLEN (hier: die erreichten Zustände der Population). Negativ = die
        Ausgangszustände derselben Population, in denen es NICHT liegen darf.

        Ohne die Negativseite misst man nur Anwesenheit, und ein Muster, das
        überall auftaucht, unterscheidet nichts (§4).
        """
        positive = [l.state() for l in runs]
        negative = [l.lg.materialize(0) for l in runs]
        return self.criterion.evaluate(positive, negative)


# ===========================================================================
# §7  Fitness für Seitwärtszüge
# ===========================================================================

def rewind_and_measure(run: "Run", path: "Travelpath", flags: dict[tuple, bool],
                       inputs_runs: list["InputRun"], criterion: "Criterion"
                       ) -> list[tuple[int, Signal | None, str]]:
    """§7 — der ECHTE Rewind, nicht nur seine Stellen.

    §7: Ein Seitwaertszug macht per Definition keinen Fortschritt zum Ziel, er
    erhaelt Information — er ist also nicht ueber Naehe zur Loesung bewertbar.
    Der Mechanismus dagegen: Reversibilitaet erlaubt, den Seitwaertsschritt NACH
    einem folgenden Aufwaertszug zurueckzuspulen und das Aufwaertsergebnis in
    der ORIGINAL-Kodierung auszudruecken, wo das Kriterium es bewerten KANN.
    Dieselbe Eigenschaft, die den Zug legal macht, macht seinen Beitrag messbar.

    §7 Geltungsbereich: nur wenn die Seitwaerts-Umkehrung NACH dem Aufwaertszug
    noch einen gueltigen Match hat. Das ist die nicht-interferierende
    Unterklasse. Ob ein Match existiert, wird hier GEPRUEFT, nicht angenommen —
    collect_reversed_matches liefert die Antwort, und leer heisst: dieser
    Seitwaertszug ist nach dem Aufwaertszug nicht mehr zurueckspulbar, also
    ausserhalb des Geltungsbereichs.

    §7: 'Der Rewind bewertet einen PFAD (seitwaerts+aufwaerts zusammen); Kredit
    auf Regelebene ist emergent ueber eine Population, nicht aus einem Rewind
    ablesbar.' Rueckgabe ist deshalb je Pfadstelle EIN Signal, keine
    Regelbewertung.

    Rueckgabe: (slot, Signal oder None, Begruendung).
    """
    from basic_machinery.reverse_compound import collect_reversed_matches
    from basic_machinery.schema import apply_compound
    from basic_machinery.compound_stub import PlainGraphLayeredStub, SimpleRegistry

    out: list[tuple[int, Signal | None, str]] = []
    for i, part in enumerate(path.parts[:-1]):
        if not flags.get(part.group, False):
            continue                                   # nicht seitwaerts
        if flags.get(path.parts[i + 1].group, False):
            continue                                   # Nachfolger nicht aufwaerts

        rewound, reasons = [], []
        for r in inputs_runs:
            keys = [k for k, g in r.layer_to_group.items() if g == part.group]
            if not keys:
                reasons.append("keine Ebene dieser Gruppe"); continue
            k = max(keys)
            base = r.lg.materialize(k - 1)
            after_sideways = r.lg.materialize(k)
            after_upward = r.state()
            fwd = run.moveworks.matcher(part.group).collect_all(base)
            if not fwd:
                reasons.append("Vorwaertsmatch nicht rekonstruierbar"); continue
            rev, _ = collect_reversed_matches(fwd, base, after_sideways)
            if not rev:
                reasons.append("Umkehrregel gebaut, aber kein Match"); continue
            # Zurueckspulen auf dem Zustand NACH dem Aufwaertszug, nicht auf
            # after_sideways — genau das ist die Frage aus §7.
            stub = PlainGraphLayeredStub(after_upward)
            try:
                apply_compound(stub, SimpleRegistry(), stub.base_key,
                               stub.new_key, rev)
                rewound.append(stub.materialize(stub.new_key))
            except Exception as e:                      # noqa: BLE001
                reasons.append(f"Rueckspulen scheiterte: {type(e).__name__}")

        if not rewound:
            out.append((i, None, "; ".join(sorted(set(reasons))) or "kein Rewind"))
            continue
        starts = [r.lg.materialize(0) for r in inputs_runs]
        out.append((i, criterion.evaluate(rewound, starts),
                    f"{len(rewound)}/{len(inputs_runs)} Eingaben zurueckgespult"))
    return out


def sideways_slots(path: "Travelpath", flags: dict[tuple, bool]) -> list[int]:
    """Nur die STELLEN, an denen ein Rewind ansetzen koennte. Billig, ohne
    Substrat — die eigentliche Bewertung macht rewind_and_measure."""
    return [i for i, b in enumerate(path.parts[:-1])
            if flags.get(b.group, False) and not flags.get(path.parts[i + 1].group, False)]


# ===========================================================================
# Die Suche
# ===========================================================================

@dataclass
class Outcome:
    path: Travelpath
    plan: tuple
    quality: float
    flags: dict[tuple, bool]
    attention: Attention
    generations: int


class GA:
    """Setzt §3 bis §10 zusammen. Sucht Baupläne — Folgen von Regelgruppen —
    und bewertet jeden über der ganzen Eingabenpopulation."""

    def __init__(self, inputs, criterion: Criterion, supply: Sequence[str],
                 seed_layer: Callable, moveworks: MoveWorks | None = None,
                 c: float = 4.0, seed: int = 0):
        self.rng = random.Random(seed)
        self.inputs = list(inputs)
        self.criterion = criterion
        self.moveworks = moveworks or MoveWorks()
        self.seed_layer = seed_layer
        self.actions = Actions(supply, self.rng)
        self.strategies = Strategies(self.actions, self.rng)
        self.attention = Attention(c=c)
        self.flags: dict[tuple, bool] = {}

    def _evaluate_plan(self, plan: Sequence[tuple]):
        run = Run(self.inputs, self.criterion, self.moveworks, self.seed_layer)
        path, runs = run.walk(plan)
        flags = commit_reversibility(run.ledger, runs, len(self.inputs))
        return path, flags, run

    def search(self, generations: int = 8, width: int = 6) -> Outcome:
        best_plan = (self.actions.fresh(),)
        best_path, self.flags, _ = self._evaluate_plan(best_plan)
        best_quality = best_path.quality(self.attention.credit)
        stall = 0

        for gen in range(generations):
            # §3: die Fruchtbarkeit bestimmt, WO gehandelt wird — auf und
            # unterhalb des besten Messpunkts, nie oberhalb.
            if best_path.signals:
                test_index = max(range(len(best_path.signals)),
                                 key=lambda i: best_path.signals[i].separation)
                self.attention.award(
                    test_index, best_path.parts,
                    best_path.signals[test_index].separation)
                weights = [self.attention.fertility(i, best_path.parts)
                            for i in range(len(best_plan))]
            else:
                weights = [1.0] * len(best_plan)

            improved = False
            for _ in range(width):
                plan = list(best_plan)
                slot = self._pick_slot(weights, len(plan))
                base = plan[slot] if slot < len(plan) else self.actions.fresh()
                for candidate in self.strategies.candidates(base, self.flags,
                                                            n=2, stall=stall):
                    attempt = plan[:slot] + [candidate] + plan[slot + 1:]
                    if self.rng.random() < 0.35:
                        attempt = attempt + [self.actions.fresh()]
                    path, flags, _ = self._evaluate_plan(tuple(attempt))
                    if path.quality(self.attention.credit) > best_quality or (
                            path.quality(self.attention.credit) == best_quality and path.depth < best_path.depth):
                        best_quality, best_path = path.quality(self.attention.credit), path
                        best_plan = tuple(attempt)
                        self.flags = flags
                        improved = True

            # Sven: konservativ bleiben, bis es nicht mehr weitergeht. `stall`
            # ist genau dieses 'nicht mehr weitergeht' und steuert, wie grob
            # die Strategien im naechsten Durchgang greifen.
            stall = 0 if improved else stall + 1

        return Outcome(best_path, tuple(best_plan), best_quality, self.flags,
                        self.attention, generations)

    def _pick_slot(self, weights: Sequence[float], n: int) -> int:
        """Fruchtbarkeit als Gradient (§3: feinkörnige Aufmerksamkeitssteuerung
        wird gegenüber Pfad-als-Populationssaat bevorzugt)."""
        if n == 0:
            return 0
        g = [max(0.0, w) for w in weights[:n]] or [1.0] * n
        if sum(g) <= 0:
            return self.rng.randrange(n)
        target = self.rng.random() * sum(g)
        run = 0.0
        for i, w in enumerate(g):
            run += w
            if run >= target:
                return i
        return n - 1
