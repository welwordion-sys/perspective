# Perspective — Gesamtdesign des genetischen Algorithmus

Stand: 2026-08-05. Führt alle vorhandenen KB-Knoten zum GA mit allem zusammen,
was in den Sitzungen vom 01.08. bis 05.08. festgelegt wurde.

**Lesehilfe zum Belegstatus.** Ohne Zusatz = von Sven festgelegt. *(gemessen)* =
in dieser Arbeit gemessen, Zahlen im Text. *(offen)* = nicht entschieden.
*(veraltet)* = im KB noch falsch, hier korrigiert.

Ergänzende Dokumente: `strukturanalyse_design.md` (Strukturensuche im Detail),
`baby_ga_funktionen.md` (Funktionsliste — enthält veraltete Stellen, siehe §15).

### Wiederkehrende Begriffe, hier einmal erklärt

**Der offene Knoten** (`rule_collapse_self_similarity`). Das System hat *eine*
Grundhandlung: eine Regel nimmt ein Stück Graph und schreibt es um. Zwei Vorhaben
scheinen etwas darüber Hinausgehendes zu brauchen — mehrere feine Regeln zu einem
gröberen Baumknoten zusammenzufassen, und beim Rekombinieren das Verbindungsstück
zwischen zwei Regelhälften zu erzeugen. Beides *scheint* eine Handlung zu
verlangen, die über Regeln herrscht statt über Daten; und sobald man die einführt,
ist die Selbstähnlichkeit gebrochen — die zweite Ebene liefe nicht mehr mit
derselben Maschinerie wie die erste. Der bevorzugte Ausweg: es braucht keine
Ausnahme, weil Regeln selbst Graphen sind, also ist „Regeln zusammenfassen"
dieselbe Umschreibhandlung eine Ebene höher. Offen bleibt, **was die erste
Umschreibung auf der Regelebene auslöst**. Dieser Knoten gehört zum späteren
graphbasierten Übergang und wird in der Babyphase bewusst umgangen (§9, §11).

**Knotenidentität trägt keine Information** (`node_identity_carries_no_information`).
Ein Knoten ist nur durch seine Struktur definiert; sein Name oder Typ trägt nichts
bei. Deshalb sind Knoten in allen Abzählungen ununterscheidbar.

**Zuschreibungsstatus.** Die KB führt zu jedem Knoten Zuschreibungen mit
`confirmed: true/false`. `false` heißt: in einer Sitzung geschrieben, von Sven noch
nicht bestätigt.

---

## 1. Was gesucht wird

### Das Ziel des GA

**Der GA sucht Travelpaths** — geordnete Folgen von Regelschichten, die von einer
Eingabe zu einem Ergebnis führen. Ein Travelpath *ist* ein Algorithmus; ihn zu
finden heißt, einen Lösungsweg entdeckt zu haben.

Woran „Ergebnis" gemessen wird, sagt der GA **nicht selbst**. Das sagt das
steckbare Fitnesskriterium (§4). Der GA ist gegenüber der Domäne gleichgültig:
Arithmetik, Buchstabenerkennung, Bilder — er sieht Graphen, Regeln und ein
Kriterium.

**Der GA darf nicht um Arithmetik herumgebaut werden.** Die Allgemeinheit trägt
das Kriterium, nicht ein Eingriff in den GA.

### Das Ziel des Arithmetiktests

Davon zu trennen: `x = number` ist die **Zielform eines Testproblems**, nicht das
Ziel des GA. Für Variablengleichungen wie `2*x+4=10`, die `encoding.py` bereits
parst, heißt gelöst: Variable isoliert auf einer Seite, dekodiertes Zahlliteral
auf der anderen.

**Kommutation und zweiseitige Gleichungsbehandlung sind Zwischenmanöver**
innerhalb dieses Tests, nicht Ziele. Wo andere KB-Knoten von „Fortschritt" oder
„Lösung" sprechen, meinen sie diese Testzielform — nicht das GA-Ziel.

Arithmetik ist außerdem nur *ein* Testproblem und noch nicht mal fertig
(Subtraktion fehlt, §16). Und es ist ein **schwaches** Testproblem für den GA: die
Regeln sind dort schon korrekt, Wiederverwendung ist trivial optimal, also kann
der Test die Strategiewahl gar nicht auf die Probe stellen. Er beweist
Lösungsfähigkeit, nicht Klugheit.

---

## 2. Vier Baustufen

| Stufe | Was |
|---|---|
| **1** | Primitiver GA erreicht überhaupt eine Lösung. Archiv wird **nur geschrieben, nie gelesen** — absichtlich. |
| **2** | Architektur liest den Aufzeichnungsgraphen und verfeinert damit den GA. Hier entsteht der Lesekanal. |
| **3** | GA wird in Graph-Architektur übersetzt — er hört auf, etwas zu sein, das *auf* dem Graphen arbeitet, und wird etwas, das *aus* dem Graphen besteht. |
| **4** | Ersetzt durch einen Traveler, der mit derselben Maschinerie auf seiner eigenen Historie arbeitet. |

Stufe 1 ist geteilt: **1a** auf dem vorhandenen Binärkanten-Substrat (die
Sicherheitsbasis, beweist dass der GA lösen kann), **1b** dasselbe auf
Hyperkanten. Beide laufen parallel; zusammengelegt wird erst, wenn Hypergraphen
bei der Leistung nachweislich mithalten — **die Schwelle dafür ist undefiniert**
*(offen)* und an die Isomorphiekosten gebunden.

**Wichtig für spätere Sitzungen:** der fehlende Lese-Kanal in Stufe 1 ist keine
Lücke. Er darf nicht „repariert" werden. Die Schreibseite existiert übrigens
schon in `layers.py` — `LayerRecord.parents` gibt Ebene-zu-Ebene-Kanten,
`travel_type` beschriftet jede Kante seitwärts/aufwärts, `provenance` trägt die
Abbildung auf Aufwärtskanten.

---

## 3. Wie ein einzelner Lauf arbeitet

Das war die Lücke, die alle früheren Knoten offen ließen: sie beschrieben die
*Evolution* des GA, nie den *einzelnen Lauf*.

**Eingang.** Der Lauf nimmt ein **steckbares Fitnesskriterium** hinter fester
Schnittstelle. Er erzeugt Regelgruppen pro Ebene und baut daraus Travelpaths.

**Wo gemessen, was gilt.** Fitness wird über einer **Ebenenmenge** ausgewertet
*(veraltet im KB: dort steht „an einer Ebene")*, gilt aber **pfadweit**. Der
Messpunkt ist ebenenlokal, die Bedeutung pfadweit. Damit löst sich die
Scheinfrage „ist die Population aus Ebenen oder Pfaden": die Ebene ist der
Messpunkt, der Pfad das Bewertete.

**Getestet wird auf einer EINGABENPOPULATION, nicht auf einer Einzeleingabe.**
Das ist keine Feinheit, sondern konstitutiv. Eine Ebene wird an mehreren Eingaben
zugleich geprüft, und ihre Fitness ist, wie konsistent sie über alle dasselbe
Richtige tut. Der Grund: **die Identität einer Ebene sind ihre Regeln.** Alle
Eingaben teilen dieselbe Regelgruppe pro Ebene — sonst würde man nicht den
Travelpath testen, sondern pro Eingabe etwas anderes, und dann wäre es kein
Algorithmus.

Die **einzige** Freiheit zwischen Eingaben ist die **Looplänge**. Damit ist der
Loop die einzige Stelle, an der Eingaben auseinanderlaufen: davor stehen alle auf
derselben Ebene, im Loop drehen sie unterschiedlich oft, danach sind sie wieder
synchron. Deshalb kann die Abbruchbedingung eines Loops nicht global sein, sondern
hängt pro Eingabe an der Stabilisierung.

*(gemessen)* Warum über Eingaben und nicht innerhalb eines Graphen: die Wiederkehr
einer Struktur innerhalb *eines* Graphen stirbt bei k≈6 — dort kommt jede Form nur
noch 1,2-mal vor. Über mehrere Eingaben hinweg lebt sie.

**Einschränkung — und der Weg heraus** *(Langzeitabsicht, siehe §11)*: die
Abhängigkeit von einer Eingabenpopulation ist eine Eigenschaft der Babyphase,
keine dauerhafte. Der GA soll **entdeckte Strukturen speichern**; damit lernt er
später, Substrate und Darstellungen wiederzuerkennen und Lösungswege aus
gespeicherten Travelpaths abzuleiten — und kann dann **auch bei Einzeleingaben
Lösungen vermuten**, statt eine Population zu brauchen.

**Fruchtbarkeit und Kredit sind EIN Mechanismus, nicht zwei** *(zu klären)*. Eine
frühere Fassung dieses Dokuments beschrieb sie als zwei Regeln und klang dabei
doppelt, weil sie funktional dasselbe sagen: Kredit ist die *Zuweisung*,
Fruchtbarkeit ist ihre *Wirkung* — mehr Ebenenerzeugung an der Stelle, die Kredit
bekam. Eine Größe, von zwei Seiten beschrieben.

Der Mechanismus, in einem Satz: **ein guter Fitnesstest macht die getestete Ebene
(auf) und den Unterbau darunter (unterhalb) fruchtbarer — nicht oberhalb — und der
Bonus fällt mit der Entfernung zum Test.**

Die Richtungsbeschränkung hat einen Grund: oberhalb des Tests ist noch nichts
gebaut und nichts bewertet, dort wäre jede Zuweisung spekulativ. Neue Erzeugung
oberhalb ist die *Folge* der Fruchtbarkeit unten, nicht ihr Empfänger. Kurz:
**Kredit nur für Erreichtes und Geprüftes, nie für Erhofftes.**

*(zu klären)* Ob du Kredit und Fruchtbarkeit als getrennte Größen willst — etwa
Kredit als gespeicherte Bewertung und Fruchtbarkeit als daraus abgeleitete
Erzeugungsrate, die auch anders gespeist werden könnte. Im aktuellen Entwurf sind
sie eins.

### Fruchtbarkeit an Loops

Ein Loop verhält sich **nicht** wie eine Folge gewöhnlicher Ebenen:

**Die Mitte eines Loops ist kein Ort für Fruchtbarkeit.** Dort zu sprießen hieße,
in einen sich wiederholenden Block hineinzuwachsen, dessen Wiederholungszahl gar
nicht festliegt — die Einfügung hätte keine bestimmte Stelle.

**Ein Loop kann nur am Ende sprießen.** Das ist die einzige Stelle mit einer
definierten Position: nach der letzten Wiederholung, unabhängig davon, wie viele es
waren.

**Für die Tiefenberechnung zählt ein Loop als EIN Baustein**, nicht als so viele
Ebenen wie Wiederholungen. Sonst würde derselbe Algorithmus je nach Eingabegröße
verschieden tief erscheinen — genau die Längenabhängigkeit, die die
Loop-Markierung auflösen soll. Das gilt auch für die Entfernung, mit der der
Fruchtbarkeitsbonus abfällt: der Loop ist ein Schritt weit, nicht n.

**Der Fitnesstest gehört normalerweise ans Ende** des Loops — gelegentlich auch an
den Anfang. Nicht dazwischen.

**Fester Wiederholungszähler ist KEIN Loop.** Eine feste Anzahl Wiederholungen mit
nachfolgenden Regeln muss von einem Loop unterschieden werden. Ein Loop ist
ausdrücklich ein Loop: unbestimmte Höhe, Abbruch an der Stabilisierung. Ein fester
Zähler ist eine ausgerollte Folge und wird wie gewöhnliche Ebenen behandelt — mit
Fruchtbarkeit an jeder Stelle und voller Tiefenzählung.

*(offen)* Woran fester Zähler und Loop im Aufzeichnungsgraphen auseinandergehalten
werden. Die Loop-Bedingung (§5) erkennt den Loop; ein fester Zähler erfüllt sie
nicht, weil keine globale Stabilität eintritt — aber ob das als Unterscheidung
ausreicht, ist ungeprüft.

**Steuerung.** Aufmerksamkeitssteuerung (feinkörnige Fruchtbarkeit als Gradient)
wird bevorzugt über Pfad-als-Populationssaat (grobkörniger Rückfall: ganze Pfade
werden Saat neuer Populationen) — „wenn realisierbar". Beides ist derselbe
Mechanismus in verschiedener Körnung. **Risiko** *(offen)*: Aufmerksamkeits-
steuerung braucht ein **örtlich aufgelöstes** Signal, nicht nur eine Zahl; ob das
aus dem Kriterium herausfällt, ist unbelegt.

**Menschliche Grenze — in der Babyphase.** Der Baby-GA kann ein Problem **nicht**
analysieren, um selbst das beste Kriterium zu finden. Das Kriterium bleibt
menschgeliefert. Das ist die bewusste Babyphasen-Grenze und genau der Punkt, an dem
der GA menschgesteuert bleibt.

**Nicht dauerhaft** *(Langzeitabsicht, §11)*: die Endform wird voraussichtlich auch
hier Vermutungen anstellen können — entweder über **gespeicherte Kriterien zu
Substraten** (dieses Substrat sah so aus, damals funktionierte jenes Kriterium)
oder durch **statistisch geleitetes Ausprobieren**. Menschgeliefert ist der
Anfangszustand, nicht das Wesen des Systems.

---

## 4. Das Fitnesskriterium

**Auslöser und Mustererkennung sind dasselbe** *(veraltet im KB: dort stehen zwei
getrennte Kriterienfamilien)*. Ein Zustand ist prüfreif, wenn das Muster vorliegt.
Es braucht keine zweite, andersartige Bedingung.

**Der einzige variable Teil ist die Herkunft des Musters:** bekannt oder
statistisch identifiziert. Bei Arithmetik ist es bekannt (`x = number` ist eine
Zielform). Bei Bilderkennung wird es statistisch gefunden.

**Beide Seiten sind Pflicht:** das Muster muss da sein wo es soll **und fehlen wo
es nicht soll**. Nur Anwesenheit zu messen ist wertlos — ein Muster, das überall
auftaucht, unterscheidet nichts.

*(gemessen)* Die Trennschärfe muss als **Differenz** gerechnet werden
(Trefferquote minus Fehlalarmquote), nicht als Produkt. Beim Produkt bekam eine
Form, die die Eingaben quer zum Label spaltet, einen guten Wert; bei identischen
Positiv- und Negativmengen kam 0,25 heraus statt 0.

**Negativsignal für Arithmetik:** chaotischer Graph (messbar mehr Entropie) oder
falsche Gleichung. *(gemessen)* strukturiert 4,99 gegen chaotisch 6,32 (Shannon
über Formenverteilung); Formenzahl 35 gegen 91.

Das Kriterium selbst wird **individuell vom Nutzer** aus bereitgestellten
Informationen für ein Problem zusammengesetzt.

---

## 5. Loops

**Loop-Bedingung, in dieser Reihenfolge:** gleiche Regelgruppe → mindestens **eine
Ebene hat erfolgreich gefeuert** → **danach** globale Stabilität. Nicht
gleichzeitig; das erfolgreiche Feuern geht der Stabilität voraus.

Der Loop wird als **Ebene unbestimmter Höhe** markiert. Das löst die
Längenabhängigkeit: ein ausgerollter Pfad löst genau eine Problemgröße (etwa eine
Bitlänge), eine markierte Schleife jede.

**Lokal unverändert heißt dagegen nur: keine vorhandene Regel interagiert damit.**
Kein Signal. Das ist auch der Grund, warum **Erhalt über Ebenen hinweg kein
Bedeutungssignal ist** — Regeln können schlecht gewählt sein und nichts anfassen.

Nebeneffekt: die Konsistenz-über-Eingaben-Fitness belohnt die Loop-Struktur
automatisch, weil ein ausgerollter Pfad über verschiedene Größen inkonsistent ist.

---

## 6. Regellegalität — zwei Regime

Legalität spaltet nach **Reversibilität**:

**Aufwärts** (irreversibel: Reduktion, Isolation) verliert Information. Legal
genau dann, wenn das Ergebnis unter dem festen 54-Regel-Reducer (`decoder.py`) zur
gleichen Zahl auswertet.

**Seitwärts** (reversibel: Kommutation, Umkodierung) erhält Information. Legal
genau dann, wenn **invertierbar** — schuldet dem Reducer nichts und darf
Kodierungen erzeugen, die er nicht verarbeiten kann.

**Grundsatz: der Reducer ist ein Korrektheits-Orakel, keine Schablone für
Regelform.** Ein früherer Entwurf machte „reduziert weiterhin unter
Arithmetikregeln" zum universellen Gate — das verbietet alternative Kodierungen,
also genau die Seitwärtszüge, für die die Architektur existiert.

### FEHLER: der Reversibilitätstest ignoriert die Eingabenpopulation

*(bestätigt am Code, 2026-08-05)* `reclassify_after_firing` in
`basic_machinery/reverse_compound.py` prüft Reversibilität an **genau einem**
Graphenpaar — `lg.materialize(base_layer)` vor dem Feuern gegen
`lg.materialize(new_layer)` danach. Ein `LayeredGraph`, also **eine Eingabe**.

Bei `reversible is True` wird der `LayerRecord` auf `SIDEWAYS` gesetzt und die
**Provenienz gelöscht**. Das Löschen ist zwingend, nicht optional: `LayerRecord`
weist im eigenen `__post_init__` einen SIDEWAYS-Datensatz zurück, der noch eine
trägt — mit der Begründung, die Quelle sei über die Regelinverse rückgewinnbar.

**Warum das ein Fehler ist.** Reversibilität ist eine Eigenschaft der Regelgruppe
**über der Eingabenpopulation**, nicht einer einzelnen Feuerung. Eine Gruppe kann
auf Eingabe A umkehrbar und auf B verlustbehaftet sein. Wird sie an A geprüft, gilt
sie als seitwärts — und für B ist die Umkehrung dann auf **keinem** Weg mehr
erreichbar: die Regelinverse trägt dort nicht, und die Provenienz ist weg. Der
Verlust ist nicht wiederherstellbar.

Verschärfend: die Prüfung ist an `1+1=2` verifiziert — dem Einzelfall, der den
Fehler nicht zeigen kann.

**Was gelten muss.** `SIDEWAYS` darf erst gesetzt werden, wenn die Umkehrung für
*alle* Eingaben der Population bewiesen ist. Ein `unverifiable` bei einer einzigen
Eingabe muss die Umklassifizierung blockieren — genauso, wie es heute schon
innerhalb *einer* Eingabe blockiert (die strikte Identitätsprüfung `is True`).
Die Provenienz darf erst fallen, wenn das für die ganze Population steht.

*(offen)* Ob die Umklassifizierung dafür verzögert wird, bis die Population
durchgelaufen ist, oder ob sie vorläufig gesetzt und bei einem Gegenbeispiel
zurückgenommen wird. Zurücknehmen ist nur möglich, solange die Provenienz noch
existiert — was gegen vorläufiges Setzen spricht.

---

## 7. Fitness für Seitwärtszüge

Ein Seitwärtszug macht per Definition keinen Fortschritt zum Ziel — er erhält
Information — also nicht über Nähe zur Lösung bewertbar.

**Mechanismus:** Reversibilität erlaubt, den Seitwärtsschritt **nach** einem
folgenden Aufwärtszug zurückzuspulen und das Aufwärtsergebnis in der
Original-Kodierung auszudrücken, wo der feste Reducer es bewerten *kann*.
Dieselbe Eigenschaft, die den Zug legal macht (Invertierbarkeit), macht seinen
Beitrag messbar — exakt, nicht heuristisch.

**Geltungsbereich:** nur wenn die Seitwärts-Umkehrung nach dem Aufwärtsschritt
noch einen gültigen Match hat. Das ist die nicht-interferierende Unterklasse, und
ihre Mitglieder sind Kommutation und Gleichungsumstellung — genau die Waypoints
aus §1.

**Der Rewind bewertet einen PFAD** (seitwärts+aufwärts zusammen); Kredit auf
Regelebene ist emergent über eine Population, nicht aus einem Rewind ablesbar.
Das deckt sich mit §3.

*(offen)* Eine Umkodierung, deren Umkehrung Struktur braucht, die der
Aufwärtszug verbraucht hat — derselbe Knoten wie `rule_collapse_self_similarity`.

---

## 8. Erzeugung — Aktionen getrennt von Strategien

Diese Trennung fehlte im KB-Knoten `ga_generator_policy` (der drei Strategien
nennt, aber keine Aktionen) und wurde am 04.08. eingeführt.
Eine frühere Liste vermischte beides.

### Aktionen an Regeln
- **rekombinieren**: Eingabemuster von Regel A, Ausgabemuster von B
- **Delta-Gruppen rekombinieren**
- **eine reversible Regel umkehren** (braucht eigene Platzhalter, weil sich beim
  Umdrehen ändert, welche Seite gematcht wird)
- **am Kern im DAG mutieren** und die abhängige Regelmenge ausgeben
  (Gruppenmutation, siehe §9)
- **frisch erzeugen** (Kaltstart)

### Aktionen an Regelgruppen
- **verschmelzen**
- **aufspalten**
- **wiederholen**

Verschmelzen und Aufspalten wirken auf **Regelgruppen**, nicht auf Ebenen.
Ebenenverschmelzung ist keine Aktion, sondern eine **Erkenntnis**: das Feststellen,
dass zwei Travelpaths gleichwertige Ergebnisse liefern und austauschbar sind. Die
Medienabhängigkeit der Regeln macht das schwierig.

### Strategien
wenig ändern · viel ändern · reversible bevorzugen · wiederholen bis
Stabilisierung (das ist der Loop) · Sideways-Jagd unter dünner Regelmenge

Dazu die Fruchtbarkeit als das, was bestimmt **wo** überhaupt gehandelt wird.

*(offen)* Mischung und Gewichtung der Strategien. **Kann auf dem Arithmetiktest
nicht gemessen werden** — die Regeln sind dort schon korrekt, Wiederverwendung ist
trivial optimal, der Test kann Strategien nicht unterscheiden. Echter Test ist
Stufe 1b.

**Verworfen:** Achsen-Variation (entlang bekannter Achsen wie Bitwert, Übertrag,
Breiten). Sie setzt vorher bekannte Struktur voraus, die der GA nicht kennen darf.
Was davon bleibt, ist Delta-Gruppen-Rekombination — keine eigene Strategie.

### Gruppenmutation

Beim Aufwärtswandern im Kern-DAG besteht an **jedem Schritt eine Chance**, dass
statt eines normalen Schritts Gruppenmutation aufgerufen wird: der Kern an dieser
Stelle wird geändert, und weil der Kern abhängige Regeln unter sich hat, gibt das
eine **ganze Regelmenge** aus. Der DAG liefert die Gruppenstruktur gratis — sie
ist schon darin kodiert.

*(offen)* Die Chance pro Schritt — fester Wert oder kernabhängig.

---

## 9. Rekombination

Eine Regel besteht aus **drei Teilen**: Eingabemuster, Ausgabemuster, operationale
Abbildung dazwischen.

Rekombination nimmt das Eingabemuster von einem Elternteil und das Ausgabemuster
vom anderen. **Die Abbildung wird nicht geerbt** — sie wird durch Mutation gebaut,
die gezielt auf der Abbildung arbeitet, bis sie gültig ist. Mutation ist damit der
**Reparatur-Operator für Abbildungen** innerhalb der Rekombination, kein
konkurrierender Erzeuger.

**In der Babyphase ist der Akt der Rekombination hardcodiert.** Die *Auswahl der
Struktur* ist das erste, was später gelockert wird — sie führt dann in den
graphbasierten Pfad, der zwei Graphen zu einem Regelgraphen verbindet.

*(offen)* Die genaue Formulierung eines Mutationsschritts auf einer Abbildung.
Dieses Abbildungs-Syntheseproblem ist **derselbe Knoten wie
`rule_collapse_self_similarity`** — und der gehört zum **späteren** graphbasierten
Übergang, nicht zur Babyphase. Er wird hier bewusst umgangen.

---

## 10. Mutationsstabilität

Gelöst am 29.05.: Stabilität kommt von **eingeschränkten Operatoren**, nicht von
Substrat-Typung. Der GA fasst den rohen Graphen nie an; kontrollierte Operatoren
tun das. Freiheit in dieser Stufe heißt: volle Freiheit *innerhalb* eines
wohlgeformten Graphen, keine außerhalb.

Die Wohlgeformtheits-Bedingung ist **Bootstrap-Gerüst**, nicht dauerhaftes
Einschmuggeln von Imperativem — sie wird zur Saat des GA-als-Graph beim Übergang
zur Selbstevolution.

*(Anmerkung)* Der Ausdruck „markerbewusst" im Ursprungsknoten ist vermutlich
unglücklich formuliert; gemeint ist, dass Information in der **Struktur** steckt,
nicht im Typ — vergleiche `node_identity_carries_no_information`.

---

## 11. Langzeitabsichten

Dieser Abschnitt hielt vorher nichts — er fehlte, und ohne ihn liest sich das
Dokument, als wäre die Babyphase das Ziel. Sie ist der Anfangszustand.

**Drei Grenzen der Babyphase sind ausdrücklich vorläufig**, nicht Wesenszüge:

### Gespeicherte Strukturen → Wiedererkennung → Ableitung

Der GA soll **entdeckte Strukturen speichern**. Darauf baut eine Kette auf:

1. **Speichern** — gefundene Strukturen bleiben erhalten, nicht nur das Ergebnis
   eines Laufs.
2. **Wiedererkennen** — daraus lernt der GA, **Substrate und Darstellungen** zu
   erkennen: „so etwas habe ich schon gesehen".
3. **Ableiten** — aus **gespeicherten Travelpaths** werden Lösungswege abgeleitet,
   statt jedes Mal neu gesucht.
4. **Vermuten** — damit kann der GA **auch bei Einzeleingaben** eine Lösung
   vermuten, ohne eine Eingabenpopulation zu brauchen.

Das hebt genau die Einschränkung auf, die §3 beschreibt: dass Fitness eine
Population braucht, weil Konsistenz nur über mehrere Eingaben messbar ist. Mit
Erinnerung wird aus Konsistenzmessung Wiedererkennung.

### Selbst vermutete Fitnesskriterien

Der Baby-GA ist auf menschgelieferte Kriterien angewiesen (§3). Die **Endform wird
voraussichtlich auch hier vermuten können**, auf zwei Wegen:

- **gespeicherte Kriterien zu Substraten** — welches Kriterium bei welcher Art
  Substrat getragen hat;
- **statistisch geleitetes Ausprobieren** — Kriterien probieren und am Verhalten
  ablesen, welches greift.

Das ist der Punkt, an dem der GA aufhört, menschgesteuert zu sein. Nicht in der
Babyphase, aber es ist die Richtung.

### Der GA als Graph

Die Baustufen 3 und 4 (§2) sind selbst Langzeitabsicht: der GA hört auf, etwas zu
sein, das *auf* dem Graphen arbeitet, und wird etwas, das *aus* dem Graphen
besteht — und wird zuletzt durch einen Traveler ersetzt, der mit derselben
Maschinerie auf seiner eigenen Historie arbeitet.

Die Wohlgeformtheits-Bedingung aus §10 ist dafür **Bootstrap-Gerüst**: sie wird zur
Saat des GA-als-Graph, nicht dauerhaft eingeschmuggeltes Imperativ.

Ebenso vorläufig: **die Rekombination ist hardcodiert** (§9), und die **Auswahl der
zu rekombinierenden Struktur** ist ausdrücklich das erste, was gelockert wird — sie
führt in den graphbasierten Pfad, der zwei Graphen zu einem Regelgraphen verbindet.
Die Verbindungsmuster einer solchen Pipeline sollen irgendwann selbst als Graph
dargestellt werden.

### Was daran offen ist

*(offen)* Speicherformat der entdeckten Strukturen, und wie Wiedererkennung an
Substraten gemessen wird. Die Klassifikation aus `strukturanalyse_design.md` §5 (Form plus Außensignatur) ist
ein Kandidat, weil sie ohnehin für Inputgraph- und Kernsuche wiederverwendbar ist —
aber die Anbindung ist nicht entworfen.

*(offen)* Ob die abgeleitete Vermutung bei Einzeleingaben geprüft werden kann, ohne
in dieselbe Populationsanforderung zurückzufallen.

---

## 12. Was der GA an Analysewerkzeug bekommt

Ausführlich in `strukturanalyse_design.md`. Hier nur die Einordnung:

**Primär:** Strukturen finden für die Fitnessfunktion **und** für die
Rekombination.
**Sekundär:** Aussagen über den Informationsgehalt einer Ebene — ebenfalls für
mögliche Beiträge zur Fitnessfunktion.
**Dritter Effekt:** Vorarbeit zur Regelsuche unter der DAG-basierten Methode.

**Der Nutzen dieser drei Zwecke bestimmt zusammen mit dem Aufwand, wie häufig die
Analysen laufen.** *(offen)* Die genauen Anwendungszeiten.

Zwei getrennte Wahrscheinlichkeitsfragen: beim Zusammensetzen (Zwischenbuchhaltung,
darf ungenau sein) und die Endstruktur samt Außenkanten (exakt, analytisch).
Max-k ist ein **Leistungsdeckel**, keine systematische Tatsache — es steckt nicht
in der Endstruktur.

---

## 13. Was schon im Code existiert

| Datei | Was |
|---|---|
| `basic_machinery/graph.py` | `PerspectiveGraph`, `Node`, `Edge`, `EdgeType`, `subgraph`, `neighbors` |
| `basic_machinery/layers.py` | `LayeredGraph` mit `materialize(layer)`, `LayerRecord`, `LayerRegistry`, `Provenance`, `TravelType` |
| `builders/travel_loop.py` | `fire_layer()`, `travel()` — Regelmenge → Matches → Ebene → reversibel? |
| `grouping/matcher.py` | `collect_all` (jede Regel, jede Bindung — nicht `dispatch`, das nach dem ersten Treffer stoppt) |
| `grouping/lockstep_final.py` | `transit_via` (Vergleich über Mediator statt Neusuche), `transitive_coverage` (wie viele Paare ein Mediatorsatz abdeckt), `skip_decision` (ob eine Suche übersprungen werden darf) |

**Der Pfad, den ein GA braucht, existiert und ist end-to-end geprüft:** neue
Regeln → anwenden → Ebene → reversibel? Verifiziert an `1+1=2`, drei Ebenen
gefeuert, Ebene 1 wurde von aufwärts auf seitwärts gehoben.

*(gemessen)* `collect_all` über die 257-Regel-Registry: 0,591 s → 0,002 s = 350×
durch Gruppierung.

*(offen)* Der Einzelregel-Feuerpfad (`layer_apply_schema`) ist noch **nicht** mit
`reclassify_after_firing` umhüllt — der Prüfung, die eine Ebene von aufwärts auf
seitwärts hebt, wenn sie sich als umkehrbar erweist. `travel_loop` deckt nur den
Verbundpfad ab, nicht den Einzelregelpfad.

---

## 14. Inkrementeller DAG

Wenn der GA neue Regeln erzeugt, muss der DAG inkrementell aktualisiert werden:
eine neue Regel gegen alle N bestehenden paaren. *(gemessen)* 1 neue Regel gegen
251 bestehende = 78,6 s; voller DAG hochgerechnet ~2,7 h.

**Betriebsregel:** ohne Mediator normaler Paarvergleich — der Rückfall macht
fehlende transitive Abdeckung zu einem Verlust an **Einsparung**, nie an
DAG-Kanten. Mediatoren **wachsen mit dem DAG**: jeder durchgeführte und
gespeicherte Vergleich ist Mediator für spätere Einfügungen.

**Transitivität ersetzt eine Suche nur bei zertifizierter Vollständigkeit** (Hub
plus eindeutiger Schnitt); sonst liefert sie **Saatpunkte**, und die Suche läuft
weiter — geführt statt blind. Das System muss verfolgen, welche Paare
unzertifiziert blieben.

*(gemessen)* Einsparung durch `transit_via` — die Funktion, die einen bekannten
Vergleich als Mediator nutzt statt neu zu suchen — gegen direkte Suche: 110× bei 20 Zielen,
146× bei 100 — Faktor **steigend** mit der Zielzahl bei festen 10 Mediatoren; der
Vorteil verschwindet, sobald Mediatoren ≥ Ziele.

**Transitivität als Ersatz bleibt unsound** außer unter der Zertifizierung: A und
C können teilen, was B nicht hat.

---

## 15. Was in der KB nachgezogen werden muss

Der Knoten `baby_ga_single_run` ist an drei Stellen überholt:

1. „Fitness wird **an einer Ebene** ausgewertet" → über einer **Ebenenmenge**.
2. Zwei getrennte **Kriterienfamilien** (restriktiv / allgemein) → *eine*
   Mustererkennung; einziger variabler Teil ist die Herkunft des Musters.
3. Die **Negativseite** fehlt ganz — sie ist Pflichtteil des Kriteriums.

Ebenfalls nicht im KB: die Aktionen/Strategien-Trennung (§8), die Loop-Reihenfolge
mit dem Feuern (§5), die Verwerfung der Achsen-Variation, und die Feststellung,
dass Ebenenverschmelzung eine Erkenntnis und keine Aktion ist.

Die fünf Zuschreibungen in `baby_ga_single_run` stehen weiter auf
`confirmed: false`.

---

## 16. Offene Punkte, gesammelt

**Blockierend für die Babyphase**
1. Subtraktion fehlt — damit ist `x + 3 = 8` als erstes GA-Problem blockiert.
   Der Mechanismus ist geprüft (16.384 Fälle, 0 Fehler), die Graph-Regeln fehlen:
   Bit-Schritt-Familie, Umkehr-Durchgang als Graph-Umschreibung, Abschluss,
   `0−n`-Rahmen. `bit_variant_generator.py` ist nicht im Repo, Ort unbekannt.
2. Anwendungszeiten der Strukturanalysen — Nutzen gegen Aufwand.

**Design**
3. Ist das Fitnesssignal örtlich auflösbar genug für Aufmerksamkeitssteuerung?
4. Chance pro Schritt für Gruppenmutation — fest oder kernabhängig?
5. Gewichtung der Erzeugungsstrategien — nur in Stufe 1b messbar.
6. Verrechnung der Paarungsgewichte zu einer Ordnung.
7. Abbildungs-Synthese bei Rekombination (= `rule_collapse_self_similarity`,
   gehört zur graphbasierten Phase).
8. Schwelle des 1a/1b-Zusammenlegungs-Gates.

**Technisch**
9. Anbindung der Strukturanalyse an `PerspectiveGraph` / `LayeredGraph` —
   ungeprüft.
10. Einzelregel-Feuerpfad nicht mit Reversibilitätsklassifikation umhüllt.
10b. **BESTÄTIGTER FEHLER (§6):** `reclassify_after_firing` prüft Reversibilität an
   einer einzigen Eingabe und löscht dabei unwiederbringlich die Provenienz.
   Muss über die Eingabenpopulation prüfen. Höchste technische Priorität, weil der
   Datenverlust nicht rückholbar ist.
10c. Unterscheidung fester Wiederholungszähler gegen echten Loop im
   Aufzeichnungsgraphen (§3) — ungeprüft, ob die Loop-Bedingung dafür reicht.
11. Selbstabbildungen einer Form für die analytische Zählung.
12. Korrelation bei großen Zielstrukturen — ungemessen. Der Dichtefall ist
    entschieden, und zwar **gegen** die Korrelation *(ERS-falsifiziert)*.

---

## 17. Vorbehalt

Alle Strukturzahlen stammen aus einem **Nachbau** der Spine-Kodierung, nicht aus
`encoding.py`. Größenordnungen tragen, genaue Formzahlen nicht.

**Ohne zu wissen, wie das Medium erzeugt wird, ist die Aussagekraft der
Wahrscheinlichkeitszahlen geschätzt, nicht bewiesen.** Es sind Messwerte, keine
Wahrheiten.
