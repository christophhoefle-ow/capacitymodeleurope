# Übergabe: Kapazitätsmodell Core-Region

Für alle, die das Modell übernehmen und das Projekt nicht kennen. Lesezeit zehn Minuten.

## Was das Modell beantwortet

Wie stark ist das Höchstspannungsnetz (220 und 380 kV) in den 13 Ländern der Core-Region ausgelastet, und wo ist noch Anschlusskapazität frei? Das Modell gibt jeder Leitung, jedem Transformator und jedem Umspannwerk eine Ampel. Es nutzt nur öffentliche Daten.

## In zehn Minuten arbeitsfähig

1. Im Repository auf Releases gehen, Eintrag model-latest, `Capacity_Model_Core.xlsx` herunterladen.
2. Das Blatt Checks öffnen. Jeder Status sollte OK sein oder verstanden werden.
3. Auf dem Blatt Dashboard in Zeile 3 Sicht, Land und Netzbetreiber wählen.
4. Auf dem Blatt Map zoomen oder ein Umspannwerk suchen.
5. Das Blatt Guide erklärt alles Weitere, auch die Grenzen des Modells.

## Wer muss was tun

Im laufenden Betrieb niemand. GitHub holt die Daten, baut die Dateien und prüft sie. Die Tabelle steht in `ANLEITUNG_GitHub.md`.

Einmal im Monat genügt ein Blick auf den Reiter Issues. Dort meldet GitHub:

* einen Abruf, der gescheitert ist (der letzte gute Stand bleibt im Modell),
* ein neues JAO-Netzmodell, das übernommen wurde, oder eines, das wegen einer Auffälligkeit nicht übernommen wurde.

## Was automatisch läuft und wie belastbar das ist

| Daten | Quelle | Automatisch? | Stand der Prüfung |
|---|---|---|---|
| Auslastung je Leitung und Stunde | JAO Publication Tool | ja, täglich | gegen einen Testserver geprüft, nicht gegen JAO selbst |
| Netzmodell (Leitungen, Transformatoren, Grenzwerte) | JAO Static Grid Model | ja, monatliche Prüfung, Übernahme nach Plausibilitätsprüfung | Übernahme mit dem Stand 03/2026 geprüft, der Abruf von der JAO-Seite noch nicht |
| Standorte der Umspannwerke | OpenStreetMap, zugeordnet vom DLR (Zenodo) | ja, monatlich | Dateiaufbau am 25.11.2026 an der echten Datei geprüft; im Repository liegt bis zum ersten Lauf ein Auszug für AT, BE, CZ, DE und einen Teil von FR |
| Ländergrenzen | Natural Earth | ja, monatlich | nur mit nachgebauten Daten geprüft, Adresse nicht getestet |
| Freie Anschlusskapazität | Veröffentlichungen der Netzbetreiber | ja, wöchentlich: 50Hertz, TransnetBW, Amprion; TenneT über einen Browser | an den echten Inhalten geprüft, außer TenneT; kein Abruf ist bisher aus GitHub gelaufen (siehe unten) |
| Netzausbauprojekte | BNetzA, TYNDP, nationale Pläne | nein, redaktionelle Tabelle | 20 Projekte, Stand je Zeile |

## Anschlusskapazität: was geht und was nicht

Die EU-Strommarktverordnung (Verordnung (EU) 2019/943, Artikel 50 Absatz 4a) verpflichtet jeden Übertragungsnetzbetreiber, die freie Anschlusskapazität je Umspannwerk zu veröffentlichen und mindestens monatlich zu aktualisieren. Ein gemeinsames Format gibt es nicht, eine Schnittstelle bietet keiner der vier deutschen Netzbetreiber. Das Modell liest deshalb die Seiten und Dateien selbst, jede Woche.

| Netzbetreiber | Was er veröffentlicht | Was das Modell liest | Stand der Prüfung |
|---|---|---|---|
| TransnetBW | Seite mit Status, frühestem Jahr und MW-Klassen je Umspannwerk | alles: Status, Jahr, Einspeise- und Lastkapazität | am echten Seiteninhalt vom 25.11.2026 geprüft (52 Umspannwerke, Stand 01.04.2026) |
| Amprion | PDF mit den Anlagen, an denen ein Anschluss voraussichtlich möglich ist, mit Jahr und Hinweisen | Status je Richtung (Einspeisung, Last) und Jahr | am echten Text der Datei von April 2026 geprüft (10 Anlagen) |
| 50Hertz | PDF mit Schaltfeld-Verfügbarkeit als Wort und MW-Klassen als Zellfarben | Schaltfeld-Status sicher; MW-Klassen, wenn die Farben eindeutig lesbar sind | Status am echten Text der Datei vom 24.08.2025 geprüft; Farbauswertung nur an einem nachgebauten PDF |
| TenneT | Tabelle der Standorte mit möglichen Anschlüssen | Tabelle über einen Browser | ungeprüft: Die Seite hat am 25.11.2026 automatische Abrufe abgewiesen. Ob der Abruf aus GitHub gelingt, zeigt erst der erste Lauf |

* **Zuordnung der Wörter:** Bei TransnetBW zählt „mittelfristig verfügbar" als verfügbar, „langfristig verfügbar" (frühestens 2035) als eingeschränkt, „nicht verfügbar" als keine. Bei 50Hertz zählt „nicht überbucht" als verfügbar, „überbucht" als eingeschränkt, „belegt" als keine. Bei Amprion wird aus „ausschließlich Lastanschlüsse möglich" keine Einspeisung, aus „Einspeisungen nur mit reduzierter Leistung" eingeschränkte Einspeisung. Das sind Annahmen des Modells; sie stehen in `config/connection_sources.yml` und lassen sich dort ändern.
* **Nicht aufgeführte Umspannwerke:** 50Hertz schreibt, dass sie derzeit keine Anschlussmöglichkeit bieten. Amprion weist auf seiner Karte zwei Kategorien aus, grün und rot („Anschlussmöglichkeit nicht gegeben“); das gelesene Dokument führt nur die grünen auf, die Karte selbst wertet das Modell nicht aus. Im Modell bleiben sie grau, bis im Blatt Parameters `P_NotListed` auf RED steht. Das gilt dann für alle Netzbetreiber mit Zeilen im Modell.
* **Namen, die das JAO-Netzmodell nicht kennt** (neue oder geplante Anlagen wie Pfullendorf oder Clusorth), haben keine Wirkung. Sie stehen mit Grund in `data/manual/grid_connection_report.csv`.
* **Verzeichnis:** Capacitypedia von ENTSO-E und DSO Entity führt je Netzbetreiber eine Seite mit Stand, Link, Format und Aktualisierung. Das Modell liest diese Seiten für alle Core-Netzbetreiber und schreibt `data/processed/connection_publications.csv`. RTE, MAVIR, HOPS und Transelectrica haben dort keine Seite (Stand 11/2026). Für die Netzbetreiber der übrigen zwölf Länder gibt es noch keinen Leser; veröffentlicht einer eine Tabelle, genügt ein Block in `config/connection_sources.yml`.
* **Wenn ein Netzbetreiber seine Seite umbaut,** scheitert der Abruf oder der Leser bricht ab, weil Status und Kapazität nicht mehr zusammenpassen. Der letzte gute Stand bleibt, GitHub meldet es, und das Blatt Checks zeigt es. Dann muss jemand die Quelle in `config/connection_sources.yml` anpassen. Das ist die Stelle, an der das Modell auf Dauer Pflege braucht.

Die Anschlussdaten gehen in die Ampel der Umspannwerke ein (das Schlechtere aus Netz und Anschluss, getrennt für Einspeisung und Entnahme). Wer nur die Netzauslastung sehen will, stellt im Blatt Parameters `P_UseConnection` auf NO.

## Was das Modell nicht sagen kann

* JAO veröffentlicht nur Leitungen, die für den grenzüberschreitenden Handel wichtig sind. Alle anderen sind grau. Grau heißt keine Daten, nicht freie Kapazität.
* Die Auslastung ist eine Prognose vor Redispatch aus der Kapazitätsberechnung, keine Messung.
* Standorte mit dem Vermerk „approximate" können um Dutzende Kilometer abweichen. Leitungen sind gerade Verbindungen, keine Trassen.
* 110 kV und Verteilnetze fehlen.

## Auffälligkeiten in den Quelldaten, die das Modell behandelt

* „St. Peter" gibt es in Österreich und bei Düsseldorf. Das Modell führt beide getrennt, mit dem Land in Klammern.
* Schreibvarianten eines Namens im JAO-Netzmodell führt `data/manual/substation_aliases.csv` zusammen.
* Die Koordinaten aus der TenneT-Datei sind auf etwa 1 km gerundet und für Umspannwerke anderer Betreiber teils weit daneben. OpenStreetMap hat deshalb Vorrang.
* Die Leitungslängen der französischen Leitungen sind Abschnittslängen. Aus ihnen lässt sich keine Lage ableiten.
* Prüflisten nach jedem Lauf: `data/manual/coordinates_report.csv`, `coordinates_line_check.csv`, `grid_connection_report.csv`.

## Wo was steht

| Frage | Datei |
|---|---|
| Einrichtung in GitHub | `ANLEITUNG_GitHub.md` |
| Betrieb, Abläufe, Sonderfälle | `docs/OPERATIONS.md` |
| Schnittstelle zwischen Pipeline und Excel | `docs/DATA_CONTRACT.md` |
| Quellen mit Lizenz | `docs/DATA_SOURCES.md`, `docs/DATENQUELLEN.md` |
| Annahmen und Schwellen | Blatt Parameters im Modell, `config/config.yml` |
| Getroffene Entscheidungen | Blatt Parameters, Abschnitt F |

## Vor der Übergabe ausfüllen

Im Blatt Guide, Abschnitt 8: Verantwortliche Person, Vertretung, Adresse des Repositories, Datum der letzten Durchsicht der Annahmen.
