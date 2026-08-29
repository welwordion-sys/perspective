# Strukturensuche: Skalierung und Abbruchbedingungen

Stand 2026-08-28. Alles hier ist **gemessen**, nicht geschätzt; zu jeder Zahl
gehört ein Reproduzierer in `tests/structure_scaling_2026_08_28/`.

Anlass: das erste nicht-arithmetische Testproblem (Buchstabenerkennung auf
einem Schwarzweiss-Pixelraster) fällt in den **dichten** Fall, für den
`strukturanalyse_design.md` selbst festhält, dass die Kantendichte die Kosten
treibt — 29 Knoten bei Grösse 8 ergeben 439 Gruppen dünn und 2,4 Millionen
dicht.

---

## 1. Zurückgenommen: das Stern-„Gegenbeispiel"

*Diese Fassung stand hier am 2026-08-28 und war falsch. Sie bleibt sichtbar,
damit niemand sie zweitverwendet.*

~~Behauptet: Häufigkeit ist nicht antiton, weil beim Stern mit 10 Blättern die
Formen mit 2/3/4/5 Knoten 10/45/120/210 Vorkommen haben — grösser also
häufiger.~~

**Der Fehler:** 210 sind Teilmengen*auswahlen*, C(10,4), keine Vorkommen.
Physisch gibt es **einen** Stern mit 10 Blättern. Also 1 gegen 10 — der
Bestandteil ist häufiger, und die Abbruchregel gilt. Die eigene Kugelmessung
sagte das bereits und wurde danebengelegt, ohne gelesen zu werden:
Häufigkeiten `[11 Einzelknoten, 10 Blattkugeln, 1 ganzer Stern]`.

Mit hinfällig: die daraufhin gebaute Schranke mit Mehrfachverwendungsfaktor
als *Ersatz* für die Antitonie, und die Einschränkung der Regel auf Support
über der Eingabenpopulation. Beides stand auf dem falschen Gegenbeispiel.

### Was allgemein gilt

Doppelzählung für ein Muster S und ein Teilmuster b, mit `t_b` = wie oft b in
*einem* S steckt und `m` = maximale Mehrfachverwendung eines b-Vorkommens:

> **Vorkommen(b) ≥ Vorkommen(S) · t_b / m**

Die ursprüngliche Regel ist der Fall `m ≤ t_b`.

**`m` ist im Allgemeinen unbeschränkt.** Extremfall vollständiger Graph,
gemessen an K₇ (`complete_graph_multiplicity.py`):

| j | 1 | 2 | 3 | 4 |
|---|---|---|---|---|
| Vorkommen | 7 | 21 | 35 | 35 |
| `m` für j in k=4 | 20 | 10 | 4 | — |

Alle Unterstrukturen sind seltener als die 4-Clique, und `m = C(n−j, k−j)`
wächst mit n ohne Schranke.

`m` misst **Fortsetzungsfreiheit**, nicht geometrische Überlappung: auf wie
viele verschiedene Arten sich ein b-Vorkommen zu einem S fortsetzen lässt.
Hoher Grad bei wenig Struktur ist der schlimmste Fall. Damit ist `m` aus der
lokalen Fortsetzbarkeit abschätzbar, ohne S zu bilden — eine Eigenschaft des
*Wirtsgraphen*, nicht des Musters.

### Bei physischen Strukturen ist `m = 1` strukturell

Nicht als Bedingung: verschiedene grosse Kugeln haben verschiedene
Mittelpunkte, die Zuordnung nach unten ist injektiv. Auch maximale Überlappung
bricht das nicht — gemessen an einem Ring mit Sehnen (Grad 3, jeder Knoten
zugleich Sternzentrum und Blatt dreier anderer): auf jeder Radiusstufe genau
16 Kugeln, die Zahl steigt nie.

**Aber** Kugeln allein finden keinen Kern mit wechselndem Delta — jede Kugel um
ihn herum sieht anders aus, also ist jede einmalig und der wiederkehrende Kern
verschwindet. Genau dieser Fall ist das Ziel von §12. Subgraphen ganz
aufzugeben geht deshalb nicht: ein Kern *ist* ein Subgraph.

Möglicher dritter Weg, **ungeprüft**: Teilmengen nicht aufzählen, sondern als
Schnitt beobachteter Kugelpaare ableiten. `correlate` rechnet Schnitte ohnehin,
benutzt sie aber nur als Grössenangabe `len(A & B)` statt als Struktur.

## 2. `max_k` ist nicht monoton im Budget

`maxk_budget_curve.py`, 3×3-Gitter mit Anhängseln, 21 Kanten:

| Budget | 1 | 5 | 9 | 13 | 17 | 21 |
|---|---|---|---|---|---|---|
| `max_k` | 21 | 431 | **1.581** | 941 | 163 | 1 |

Der Gipfel liegt grob bei der halben Kantenzahl; bei Budget = Gesamtkantenzahl
ist die einzige maximale Struktur der ganze Graph. Budgets von 2–4 auf einem
12×12-Gitter (408 Kanten) liegen bei **1 %** — also im steilsten Anstieg, dem
denkbar ungünstigsten Punkt. Die andere Seite der Kurve ist nicht erreichbar:
4×4 bricht schon bei Budget 10 nach 90 s ab.

## 3. Breite zuerst macht Phase 1 berechenbar — bleibt aber unvollständig

Vollständige Kugeln `B(v,r)` statt aller zusammenhängenden Teilmengen
(`balls_vs_subsets.py`), 12×12-Gitter mit gezeichnetem T:

| | Teilmengen | Kugeln |
|---|---|---|
| Budget 5 | 72.431 Strukturen, 155 s | 559 Kugeln, 0,2 s |
| Budget 12 | nicht erreichbar | 580 Kugeln, 0,2 s |
| Budget 30 | nicht erreichbar | 755 Kugeln, 1,3 s, bis 25 Knoten |

Eine Kugel ist durch Mittelpunkt und Radius bestimmt: Aufzählung statt
Kombinatorik.

**Vorbehalt, der bestehen bleibt:** Kugeln erfassen *nicht alle Subgraphen*.
Das ist eine unvollständige Strategie, kein gleichwertiger Ersatz. Sie ist bei
dichten, regelmässigen Graphen erforderlich, nicht überall richtig.

## 4. Korrelation ist keine Sparmassnahme

`correlation_vs_budget.py`, k=3 gegen k=6, `min_share=0.0`:

| Graph | Dichte | Korrelation | Budgetverdopplung |
|---|---|---|---|
| Kette n=20 | 1,9 | 0,04 s | 0,00 s |
| Binärbaum n=31 | 1,9 | 0,85 s | 0,10 s |
| Spine 4bit | 2,4 | 0,29 s | 0,04 s |
| Gitter 5×5 | 3,2 | 14,1 s | 1,1 s |
| Zufall n=25 m=50 | 4,0 | 71,3 s | 5,7 s |

Budgetverdopplung ist durchweg rund **10× schneller**, ohne Umkehr bei höherer
Dichte. Grund: Korrelation zählt *Paare*, quadratisch in `max_k`, während
`find_structures` durch das Kantenbudget beschnitten bleibt. Bei
`Zufall n=25 m=50` erzeugen 412 maximale Strukturen 68.984 Korrelationen gegen
14.914 Strukturen bei Budget 6.

Als **Erkenntnisinstrument** bleibt sie, wofür sie gebaut ist: die gerichtete
Aussage, welche Form zu welchem Anteil in welchen Verbund eingeht (§12). Als
Ersparnis trägt sie nicht.

Zwei Vorbehalte: nur bei k=3 gemessen — bei grösserem k könnte sich das
Verhältnis drehen, weil `find_structures` exponentiell und Paare nur
quadratisch wachsen. Und mit Kugeln statt Teilmengen kehrt sich das Bild um
(620 Kugeln, 9.706 Paare).

## 5. Häufigkeit gehört vor die Diagnose

Ohne statistisch relevante Häufigkeit misst eine Korrelation nichts: kommt eine
Quellform einmal vor, ist ihre `coverage` 1/1 = 100 %, unabhängig vom Inhalt.

`frequency_first.py`, Kugelbudget 16 auf dem 12×12-T:

| Quellschwelle | Quellformen | Paare | Verbundformen | davon 1× | Zeit |
|---|---|---|---|---|---|
| 1 (heute) | 22 | 9.706 | 744 | 259 | 7,0 s |
| 5 | 11 | 8.817 | 364 | 75 | 5,7 s |
| 20 | 5 | 5.573 | **75** | **2** | **1,6 s** |

Verlustfrei, weil ein häufig mit einem Delta korrelierender Kern auch eine
häufige Verschmelzung hat. Und billiger, weil Formen zählen ein `form()` je
Struktur kostet (620) statt je Vereinigung (7.010).

**Lücke im Code:** `correlate` filtert per `min_share` nur die *Quellform*. Die
*Verbundform* wird gar nicht gefiltert — ein Verbund mit einem einzigen
Vorkommen erzeugt trotzdem eine Zeile.

## 6. Zwei verlustfreie Einsparungen in `correlate`

Beide ohne Semantikänderung; die gerichteten Zeilen bleiben vollständig.

1. **Doppelte Vereinigung.** Die Vereinigung wird aus beiden Richtungen
   berechnet, obwohl die Verbundform identisch ist — Faktor 2.
2. **Cache über der Vereinigung.** Verschiedene Paare ergeben dieselbe
   Vereinigung, `(A−e)+(B+e)` und `A+B`. Gemessen 24–28 % der `form()`-Aufrufe
   gespart (`union_cache.py`); 5.934 von 7.010 Vereinigungen entstehen aus
   genau einem Paar, der Rest bis zu siebenfach.

Zusammen grob 60 % weniger Formberechnungen — die teuerste Einzeloperation.

**Vorab bestimmbar:** ein billiger Schlüssel `(Form A, Form B, Schnittgrösse)`
legt die Verbundform in **64,9 %** der Fälle eindeutig fest (450 Schlüssel für
744 Verbundformen, 158 mehrdeutig). Eine feinere Lageangabe als die blosse
Schnittgrösse dürfte die Quote heben — ungemessen.

## 7. Was `touching` zählt

Der weiteste der denkbaren Begriffe: Reichweite = Knoten ∪ Rand, also gelten
auch Strukturen als berührend, die sich nur einen Nachbarknoten teilen, ohne
zusammenzuhängen. Überlappung und Nachbarschaft schliessen sich nicht aus
(1590 von 1896 Kandidaten sind beides).

Disjunkte Paare werden **nicht** gezählt. Strukturen sind `frozenset`s und
werden **nicht** doppelt gezählt — der gemessene Faktor 2,00 betraf geordnete
Berührungen in der Korrelation, nicht die Strukturenzahl.

## 8. Was das für das Pixelraster heisst

Bei 12×12 mit einem gezeichneten T erzeugen die 125 *leeren* Pixel die Masse,
nicht der Buchstabe: 51.974 maximale Strukturen bilden 190 Formen. Von den 29
Formen mit genau einem Vorkommen bei Budget 30 stammt **keine einzige** allein
vom Buchstaben — 12 sind reine Gitterrand-Artefakte, 17 berühren Rand und
Buchstaben. Auf einem umlaufenden oder unendlichen Gitter bliebe vermutlich
nichts davon übrig.

Offen und nicht entschieden: ob das leere Gitter überhaupt im Graphen stehen
muss, oder nur die gesetzten Pixel und ihre Nachbarschaft (beim T rund 19 statt
288 Knoten, also die Grössenordnung des Arithmetik-Spine).

## Reproduzierer

| Datei | prüft |
|---|---|
| `complete_graph_multiplicity.py` | §1, Extremfall K₇ |
| `maxk_budget_curve.py` | §2 |
| `balls_vs_subsets.py` | §3 |
| `correlation_vs_budget.py` | §4 |
| `frequency_first.py` | §5 |
| `union_cache.py` | §6 |

> Die Gitterzahlen unten sind Einbettungszahlen in *einem* Graphen und über
> freie Teilmengen gebildet. Sie beschreiben **Kosten** korrekt. Ob sie ein
> brauchbares **Häufigkeitsmass** sind, hängt an der offenen Frage, welche
> Strukturen überhaupt gezählt werden sollen (§1).
