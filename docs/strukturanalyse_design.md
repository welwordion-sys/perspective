# Strukturanalyse — vollständige Designdokumentation

Stand: 2026-08-05. Ersetzt `strukturensuche_phasen.md` (dort fehlten Zwecke,
Parameterklassifikation und das Bezugsklassenmodell).

Alles Gemessene ist als solches ausgewiesen. Alles Ungemessene steht unter
„Offen". Wo eine Entscheidung von Sven kommt, steht sie ohne Beleg — sie ist
Festlegung, nicht Befund.

---

## 0. Wozu das Ganze — drei Zwecke, nach Rang

**Primär: Strukturen finden für die Fitnessfunktion und für die Rekombination.**
Das ist der Grund, warum die Methoden existieren. Beides braucht Kandidaten:
die Fitnessfunktion braucht Muster, die Rekombination braucht Teile.

**Sekundär: Aussagen über den Informationsgehalt einer Ebene** — ebenfalls für
eventuelle Beiträge zur Fitnessfunktion.

**Dritter Effekt: Vorarbeit zur Regelsuche** unter der DAG-basierten Methode.

Die Fitnessfunktion selbst wird **individuell vom Nutzer** aus bereitgestellten
Informationen für ein Problem zusammengesetzt. Die Methoden hier liefern Material,
nicht das Kriterium.

**Der Nutzen dieser drei Zwecke bestimmt zusammen mit dem Aufwand, wie häufig
oder selten die Analysen eingesetzt werden.** Die genauen Anwendungszeiten sind
noch zu definieren — das ist der wichtigste offene Punkt, weil er über die
Praxistauglichkeit entscheidet.

---

## 1. Was benutzt wird — vorhandene Bausteine

Nicht neu erfinden. Im Repo `welwordion-sys/perspective` existieren:

| Datei | Was |
|---|---|
| `basic_machinery/graph.py` | `PerspectiveGraph`, `Node`, `Edge`, `EdgeType`; `subgraph`, `neighbors`, `edges_from/to` nach Typ |
| `basic_machinery/layers.py` | `LayeredGraph` mit `materialize(layer)`, `LayerRecord`, `LayerRegistry` (`reclassify`, `is_upward`), `Provenance`, `TravelType`, `Disposition` |

Eine Ebene **trägt** einen Graphen; `materialize(layer)` gibt ihn heraus.
Eigene Graph- oder Level-Typen sind Doppelarbeit und kennen weder Provenienz
noch Reversibilitätsklassifikation.

**Graphen auf einer Ebene müssen nicht zusammenhängen.** Max-k-Strukturen sind es
per Definition — daher müssen echte disjunkte Kombinationen nicht beachtet werden.

---

## 2. Grundentscheidungen

**Budget zählt nur Innenkanten.** Zählte man Außenkanten mit, könnte ein Knoten
mit mehr als `budget` Kanten *nie* Teil irgendeiner Struktur sein — schon allein
stehend sprengt er das Budget.

**Kreuzungen beschränken nie die Aufzählung**, nur die Klassifikation am Ende.

**Struktur-Identität ohne Kreuzungen**, damit Formen zusammenfallen und Häufigkeit
zählbar wird. Kreuzungen dienen der Bewertung.

**Reihenfolge:** (1) finden mit Innenkanten-Budget, (2) per Korrelation
zusammensetzen, (3) Außenkanten anhängen und klassifizieren.

**Max-k ist ein Leistungsdeckel, keine systematisch unumstößliche Tatsache.**
Es steckt nicht in der Endstruktur — deshalb ist die Endauswertung analytisch
möglich, ohne Stichprobe.

---

## 3. Phase 1 — Finden

```
FINDE_STRUKTUREN(graph, budget):
    stufe = { {v} : v Knoten }
    alle  = stufe
    wiederhole:
        neu = MENGE()                    # Mengensemantik IST der Duplikattest
        für jede struktur s in stufe:
            für jeden nachbarn u außerhalb s:
                kandidat = s ∪ {u}
                wenn innenkanten(kandidat) <= budget:
                    neu.hinzufügen(kandidat)
        wenn neu leer: abbrechen
        alle = alle ∪ neu;  stufe = neu
    max_k = { s in alle : kein nachbar passt noch ins budget }
```

`a+bc` und `ab+c` ergeben dieselbe Knotenmenge und fallen beim Einfügen zusammen.
Ein zusätzliches `neu minus alle` fängt **gemessen null** weitere.

Jede kleinere Struktur steckt in mindestens einer Max-k-Struktur (gemessen: 0
Waisen auf jeder Stufe). Ausnahme nur bei abgetrennten Stücken kleiner als k.

---

## 4. Phase 2 — Korrelation

### Form, kanonisch per Verfeinerung

Labels iterativ aus Nachbarsignatur (Typ, Richtung, Nachbarlabel) verdichten, bis
stabil. **Nicht** alle Permutationen — das ist fakultativ und bricht ab k≈7
zusammen. Einschränkung: starke, aber keine perfekte Unterscheidung.

### Buchführung

Index `knoten -> welche Strukturen ihn enthalten`. Liefert berührende Strukturen
direkt. Gemessen nur 1,2× auf kleinem Graphen — zahlt sich erst bei Größe aus.

### Der Test

```
für jede Form A mit vorkommen >= aufrunden(|max_k| * mindest_anteil):
    für jedes vorkommen o von A (index i):
        für jedes j in BERÜHRENDE(i) mit i < j:
            treffer[FORM(o ∪ max_k[j])].hinzufügen(i)
    deckung(A -> vf) = |treffer[vf]| / |vorkommen(A)|
```

**Kein Zusammenhangstest.** Berühren sich zwei je zusammenhängende Strukturen,
hängt die Vereinigung zwangsläufig zusammen — gemessen 0 von 1.896 Kandidaten
unzusammenhängend.

**Überlappung und Nachbarschaft schließen sich nicht aus** — 1.590 von 1.896
sind beides. Eine Bedingung, nicht zwei Fälle.

**Kein `i < j`.** ~~`a+b` und `b+a` sind derselbe Verbund.~~ *Zurückgenommen
2026-08-14.* Der Verbund ist derselbe, die Korrelation nicht — sie ist gerichtet.
Der Filter schrieb den Verbund nur der Form mit dem kleineren Index gut und warf
die Gegenrichtung weg; welche Hälfte überlebte, entschied die Indexvergabe.
Entdoppelt wird ohnehin schon durch die Mengensemantik von `hits[f]`.
Reproduzierer: `abschalt_correlate_ij.py`.

**Größenabdeckung in einem Durchlauf:** Schnittmenge leer → 2k; Schnittmenge m → 2k−m.
Gemessen bei k=4 gegen die Wahrheit: 78/78, 123/123, 192/192 bei 1.225 Prüfungen.
Ohne Überlappung nur 78/78, 114/123, 190/192 bei 3.650 Prüfungen — dreimal teurer
und lückenhaft.

**Korrelation ist asymmetrisch** und wird gerichtet geführt. Gemessen nach der
Korrektur: 1.122 Korrelationen, 36 asymmetrische Paare, invariant unter fünf
Indexvergaben; Beispiel eine Seite 100 %, die andere 67 %.

*Die früheren Zahlen (618 Korrelationen, 19 asymmetrische Paare, „eine Seite
100 %, andere 44–56 %") waren Artefakte des `i<j`-Filters und sind ungültig.
Der Befund „Korrelation IST asymmetrisch" bleibt — er wird durch die Korrektur
stärker, nicht schwächer: 36 statt 19 Paare, und jetzt reihenfolgeunabhängig.*

**Volle Deckung ist zu streng** — Kerngruppen sind per Definition mit
verschiedenen Strukturen verbunden.

---

## 5. Phase 3 — Klassifikation

Form **plus** Außensignatur (Typ, Richtung, je Knoten). Der Transitiongraph
zeichnet Strukturen bereits innen/außen getrennt auf — die Klassifikation ist
daher teilweise für Inputgraph-Suche und Kernsuche wiederverwendbar.

---

## 6. Zwei getrennte Wahrscheinlichkeitsfragen

Das ist die Trennung, an der eine frühere Fassung gescheitert ist (eine einzige
multiplizierte Bewertung für beides).

**(a) Beim Zusammensetzen: gehören diese Teile zusammen?**
Zwischenbuchhaltung. Nutzt Deckung, Zonengröße, Max-k-Auswertungen. Muss nur gut
genug sein, um Paarungen zu ordnen — **darf ungenau sein**.

**(b) Die Endstruktur: wie wahrscheinlich ist sie?**
Eigene Analyse auf dem fertigen Gebilde samt Außenkanten. **Exakt, analytisch,
keine Stichprobe.**

---

## 7. Bezugsklasse einer gefundenen Einzelstruktur

Randkantenfreier Kern, zusammenhängend, keine disjunkten Graphen — plus eine
**kantenzahl-erhaltende Erweiterung**: j angehängte Knoten mit je *einer* Kante,
j = Zahl der Randkanten, nur an Kernknoten (keine Ketten untereinander).

Zwei Kantentypen, gerichtet, keine doppelten Kanten.

```
Kernzahl    = alle zusammenhängenden Kerne auf k Knoten mit e Kanten
Anhang      = (k * 2 Richtungen * 2 Typen)^j / j!      # Knoten ununterscheidbar
Bezugsklasse = Kernzahl * Anhang
P(Struktur) = Realisierungen dieser Form / Bezugsklasse
```

**Exakt abgezählt** (Selbstschleifen erlaubt):

| k | e | zusammenh. Kerne | Formen | P(häufigste Form) |
|---|---|---|---|---|
| 4 | 3 | 1.024 | 52 | 2,34·10⁻² |
| 4 | 4 | 16.640 | 751 | 1,44·10⁻³ |
| 5 | 4 | 32.000 | 331 | 3,75·10⁻³ |
| 5 | 5 | 739.328 | 6.742 | 1,62·10⁻⁴ |

Beispiel k=5, e=4, j=3: Bezugsklasse 42.666.667, P = 2,81·10⁻⁶.

**Beschriftet oder formbasiert ist rechnerisch fast gleichgültig** — 2,81·10⁻⁶
gegen 2,27·10⁻⁶, nur 24 % Unterschied, obwohl die Bezugsklassen um Faktor 97
auseinanderliegen. Der Zähler wächst mit dem Nenner; die Knotenidentität kürzt
sich weitgehend heraus.

**Nebenbefund zur Größenabhängigkeit:** von (4,4) zu (5,4) verdoppelt sich die
Kernzahl, aber die Formenzahl *sinkt* von 751 auf 331. Bei mehr Knoten und
gleichen Kanten sind Formen dünner verteilt und häufiger. Das ist die
Größenabhängigkeit als echte Abzählung — nicht als geratener Exponent.

---

## 8. Parameter, nach Art getrennt

### Aus dem Medium abgeleitet — nicht frei setzbar
- **Selbstschleifen als Kantenplatz**: genau dann, wenn das Medium sie hat.
  Wirkt erst bei kantenreicheren Kernen — bei k=5, e=5 halbiert ihr Wegfall die
  Formenzahl (6.742 → 3.744); bei (4,3) und (5,4) ändern sie nichts.
- **Zahl der Kantentypen.**
- **Maximale Kanten pro Knoten**, falls die dritte Maßvariante genutzt wird.

### Festgelegt — keine Wahl mehr
- Knoten sind nur durch ihre Struktur definiert, also **ununterscheidbar**.
- Anhang wird durch **j!** geteilt.
- Zusatzknoten nur an **Kernknoten**, je nur **eine** Kante.
- Budget zählt nur **Innenkanten**.
- Bezugsart für Substratanalyse: **absoluter Zufall**, nicht gradserhaltend.

### Echt einstellbar
- **`budget`** — Obergrenze der Innenkanten.
- **`mindest_anteil`** — Mindestvorkommen als Prozentanteil des Gesamtaufkommens,
  aufgerundet auf ganze n. Gemessen bei 56 Strukturen: 1 % → 35 von 35 Formen
  bleiben, 2 % → 16, 5 % → 5, 10 % → 0.
- **Gewichte der Paarungsheuristik** — Deckung, Größe, Zonengröße. Getrennt
  einstellbar; **wie sie verrechnet werden, ist noch nicht festgelegt.**
- **Zahl der Vergleichsläufe**, soweit noch Stichproben nötig sind.

---

## 9. Substratanalyse und Negativsignal

Für die blinde Analyse eines Substrats ohne entworfene Regeln ist die Bezugsart
**absoluter Zufall** (gleiche Knoten- und Kantenzahl, Typen gleichverteilt).
Gradserhaltendes Verwürfeln ist verworfen: es backt die Substratstruktur in die
Bezugsgröße ein und versteckt genau das, was sichtbar werden soll.

Gemessen, 21 Knoten / 25 Kanten / Budget 4:

| Bezugsart | Formen nur echt | Anreicherung |
|---|---|---|
| absoluter Zufall | 4 (bzw. 7 in einem zweiten Lauf) | 15–60× |
| gradserhaltend | 0 | 3–9× |

Der Zufall erzeugt im Schnitt **82,8–85,9** verschiedene Formen, das echte
Substrat nur **35**. **Die Einschränkung des Formenraums ist die Information, die
die Kodierung trägt.**

**Negativsignal für Arithmetik:** chaotischer Graph (messbar mehr Entropie) oder
falsche Gleichung. Gemessen: strukturiert 4,99 gegen chaotisch 6,32 (Shannon über
Formenverteilung); Formenzahl 35 gegen 91.

**Erhalt über Ebenen hinweg ist kein Bedeutungssignal** — Regeln können schlecht
gewählt sein und schlicht nichts verändern.

---

## 10. Kosten, gemessen

**Kantendichte treibt die Kosten, nicht die Knotenzahl.** 29 Knoten, Größe 8:
439 Gruppen dünn, 19.522 bei +15 Kanten, 2,4 Mio dicht.

**Vollständige Aufzählung** vervierfacht sich pro zusätzlichem Bit: 6-Bit-Operanden
130.671 Gruppen in 5 s; 10-Bit ≈ 33 Mio ≈ 20 min; 12-Bit nicht machbar.

**Kantendeckel vor Knotendeckel** — bei Dichte 305.000 statt 578.000 Gruppen,
weil er dünne Stellen tief wachsen lässt und dichte früh abschneidet.

**Direkte Aufzählung gewinnt gegen Korrelation** — auf dünnen Graphen *und* bei
steigender Dichte. Falsifiziert (ERS `s19_korrelation_dichte`): dass Korrelation
sich bei Dichte auszahlt. Verhältnis fällt von 0,77× auf 0,33×, und sie wird
zusätzlich unvollständig (128.006 statt 140.846 Strukturen bei 81 Kanten).

**Bedeutungssignale sind gegenläufig:** Häufigkeit findet kleine wiederkehrende
Bausteine; wenige Außenkanten findet große abgeschlossene Einheiten (gemessen:
Schnitt 1 liefert den kompletten Operanden). Bei k≈5 ist beides schwach.

**Wiederkehr innerhalb eines Graphen stirbt bei k≈6** (nur 1,2 Stellen je Form,
mit Kreuzungen in der Identität) — sie lebt nur über mehrere Eingaben.

---

## 11. Vorbehalt zur Aussagekraft

**Ohne zu wissen, wie das Medium erzeugt wird, ist die Aussagekraft dieser Zahlen
geschätzt, nicht bewiesen.** Es sind Messwerte, keine Wahrheiten. Die drei
Maßvarianten (alle möglichen Graphen / kanten- und knotenerhaltende Umformung /
Graphenermittlung mit maximal k Kanten pro Knoten aus dem Substrat) sind
Datenpunkte mit unterschiedlicher Nähe zur Frage, nicht konkurrierende Wahrheiten.

Alle Zahlen in diesem Dokument stammen aus einem **Nachbau** der Spine-Kodierung,
nicht aus `encoding.py`. Größenordnungen tragen, genaue Formzahlen nicht.

---

## 12. Offen

1. **Anwendungszeiten der Analysen** — wann und wie oft, aus Nutzen gegen Aufwand.
   Wichtigster offener Punkt.
2. **Verrechnung der Paarungsgewichte** zu einer Ordnung. Eine frühere Fassung
   multiplizierte sie; das war Erfindung, keine Festlegung.
3. **Selbstabbildungen einer Form** (Automorphismen) für die analytische Zählung.
   Die Verfeinerung liefert sie nicht.
4. **Verfeinerung ist keine perfekte Formunterscheidung** — seltene Kollisionen.
5. **Korrelation bei großen Zielstrukturen** — ungemessen; nur der Dichtefall ist
   entschieden (und zwar gegen die Korrelation).
6. **Anbindung an `PerspectiveGraph` und `LayeredGraph`** — nicht geprüft.
