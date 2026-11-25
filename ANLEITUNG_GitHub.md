# GitHub einrichten, Schritt für Schritt

Ziel: Das Repository liegt in GitHub. Danach holt GitHub alle Daten selbst, baut das Excel-Modell selbst und meldet sich nur, wenn etwas nicht klappt. Niemand muss Daten von Hand eintragen oder herunterladen.

## Was danach von allein läuft

| Ablauf in GitHub (Reiter Actions) | Was er tut | Wann |
|---|---|---|
| Fetch JAO utilization | holt die Auslastung aller 16 Netzbetreiber von JAO | täglich 20:15 UTC |
| Fetch connection capacity | liest die Veröffentlichungen der Netzbetreiber zur freien Anschlusskapazität je Umspannwerk (50Hertz, TransnetBW, Amprion; TenneT über einen Browser, noch ungeprüft), dazu das Verzeichnis Capacitypedia für alle Core-Netzbetreiber | montags 04:00 UTC |
| Build Excel model | baut beide Excel-Dateien und die Browser-Karte, rechnet sie durch, prüft sie und legt sie unter Releases ab | montags 05:30 UTC und nach jedem neuen Netzmodell oder neuen Geodaten |
| Update network model | prüft, ob JAO ein neues Netzmodell veröffentlicht hat, lädt es, prüft es und übernimmt es | am 1. jedes Monats |
| Update map geodata | lädt die Standorte der Umspannwerke (OpenStreetMap) und die Ländergrenzen (Natural Earth) | am 2. jedes Monats |
| Check TYNDP project data | zeigt den Aufbau der europäischen Projektliste (nur zur Vorbereitung, ändert nichts) | nur von Hand |

Scheitert ein Abruf, bleibt der letzte gute Stand im Modell und GitHub legt unter Issues eine Meldung an. Der Reiter Issues ist damit die einzige Stelle, die jemand gelegentlich ansehen sollte.

Noch nicht automatisch: die Tabelle der Netzausbauprojekte (`data/static/grid_expansion_projects.csv`). Dafür gibt es keine öffentliche Quelle mit Status in maschinenlesbarer Form, sie wird redaktionell gepflegt.

## Vorher kurz klären

* Wo soll das Repository liegen? Für den ersten Test reicht ein eigenes privates Repository. Für den Betrieb besser in der OW-Organisation, sobald der Zugang da ist (Termin am 30.11. mit Felix v. Tiedemann). Der Umzug später ist einfach: Dateien neu hochladen.
* Öffentlich oder privat? Die Datei `Capacity_Model_Core_refreshable.xlsx` holt die Daten direkt aus GitHub. Das klappt ohne Zusatz nur bei einem öffentlichen Repository. Bei einem privaten Repository nehmen Sie die Datei ohne Verbindungen aus dem Release (sie wird jede Woche neu gebaut) oder Power Query mit Zugangscode (siehe `docs/POWER_QUERY.md`).
* Das Repository enthält abgeleitete öffentliche Daten (Auslastungen je Leitung, Standorte aus OpenStreetMap). Ob diese veröffentlicht werden dürfen, vorher kurz intern klären. Die OpenStreetMap-Daten brauchen den Hinweis „© OpenStreetMap-Mitwirkende" (ODbL).

## Schritt 1: Dateien vorbereiten

Die ZIP-Datei `github-upload.zip` mit Rechtsklick und Alle extrahieren entpacken. Ein Doppelklick reicht nicht: Er zeigt nur den Inhalt, und aus dieser Ansicht lassen sich die Ordner nicht zuverlässig in den Browser ziehen.

Im entpackten Ordner liegen zwei Ordner. Zusammen ergeben sie das Repository. Es sind zwei, weil GitHub im Browser höchstens 100 Dateien auf einmal annimmt.

| Ordner | Inhalt | Dateien |
|---|---|---|
| `Schritt_1` | `config`, `docs`, `excel`, `scripts`, `src`, `.gitignore`, `ANLEITUNG_GitHub.md`, `README.md`, `requirements.txt` | 68 |
| `Schritt_2` | `.github`, `data`, `tests` | 63 |

## Schritt 2: Repository anlegen

Auf GitHub oben rechts auf das Pluszeichen klicken, dann New repository. Name zum Beispiel `capacity-model`. Private oder Public wählen, dann Create repository.

Ein Repository, das schon eine README enthält, geht genauso: Sie wird beim Hochladen ersetzt.

## Schritt 3: Dateien hochladen

GitHub übernimmt Ordner nur, wenn sie mit der Maus in das Browserfenster gezogen werden. Der Link choose your files öffnet eine Dateiauswahl, und die nimmt keine Ordner an.

1. Auf der Startseite des Repositories Add file wählen, dann Upload files.
2. Das Explorer-Fenster neben den Browser legen. Den Ordner `Schritt_1` öffnen, mit Strg+A alles darin markieren und auf die Fläche Drag files here im Browser ziehen.
3. Warten, bis GitHub die Dateien auflistet. Dass die Ordner mitgekommen sind, sehen Sie am Pfad vor dem Dateinamen, zum Beispiel `src/capmodel/geo.py`. Dann unten Commit changes.
4. Wieder Add file, Upload files, und dasselbe mit dem Inhalt von `Schritt_2`.

Danach prüfen: Die Startseite des Repositories zeigt acht Ordner und vier Dateien, nämlich `.github`, `config`, `data`, `docs`, `excel`, `scripts`, `src`, `tests` sowie `.gitignore`, `ANLEITUNG_GitHub.md`, `README.md` und `requirements.txt`.

Steht dort ein Ordner `Schritt_1` oder `Schritt_2`, wurde der Ordner selbst statt seines Inhalts gezogen. Dann diesen Ordner in GitHub öffnen, oben rechts über die drei Punkte Delete directory wählen und den Inhalt neu hochladen.

Nicht über einen Codespace hochladen: Von dort lassen sich die Dateien in `.github/workflows` nicht speichern, GitHub lehnt das ab.

## Schritt 4: Rechte für die Automatisierung

Settings, dann Actions, dann General. Ganz unten bei Workflow permissions die Option Read and write permissions wählen und Save klicken. Ohne diesen Schritt kann kein Ablauf Daten speichern oder eine Meldung anlegen.

Prüfen Sie außerdem unter Settings, General, Features, dass Issues eingeschaltet ist. Dorthin schreibt GitHub seine Meldungen.

## Schritt 5: Einmal alles von Hand anstoßen

Reiter Actions öffnen. Fragt GitHub, ob die Workflows aktiviert werden sollen, mit I understand my workflows, go ahead and enable them bestätigen. Dann nacheinander, jeweils links den Ablauf anklicken und rechts Run workflow:

1. **Update map geodata** (etwa 5 Minuten). Danach haben die Umspannwerke aller 13 Länder ihre echten Standorte und die Karte echte Ländergrenzen.
2. **Fetch connection capacity** (etwa 5 Minuten). Wird der Lauf rot, obwohl die meisten Quellen gelesen wurden, liegt es an einer einzelnen Quelle (siehe Meldung unter Issues); die übrigen sind trotzdem gespeichert.
3. **Fetch JAO utilization**: bei Catch up from und Catch up to das gestrige Datum im Format JJJJ-MM-TT eintragen (5 bis 20 Minuten).
4. **Build Excel model** (15 bis 30 Minuten). Startet nach Punkt 1 auch von allein.

Grüner Haken: der Ablauf hat geklappt. Rotes Kreuz: den Lauf öffnen und den rot markierten Schritt aufklappen (Tabelle unten).

Wichtig: Alle Abrufe sind bisher nur gegen Testdaten geprüft, nicht gegen die echten Server. Sehen Sie sich die ersten Läufe bitte genau an. Bei JAO, bei den Geodaten und bei 50Hertz kann der erste echte Lauf eine Anpassung nötig machen.

## Schritt 6: Excel-Modell holen

Seitenleiste Releases im Repository, Eintrag model-latest. Dort liegen mit festen Links, die sich nie ändern:

* `Capacity_Model_Core_refreshable.xlsx` mit Verbindungen auf Ihr Repository. Öffnen, Bearbeitung aktivieren, Inhalte aktivieren, dann Daten und Alle aktualisieren.
* `Capacity_Model_Core.xlsx` ohne Verbindungen (Stand vom letzten Montag).
* `network_map.html`: dieselbe Karte auf echtem Kartenhintergrund, im Browser öffnen (braucht Internet).

Im Repository selbst zeigt GitHub die Datei `data/processed/network_map.geojson` als bewegliche Karte an.

Im Excel-Modell erklärt das erste Blatt Guide die Bedienung. Die Schnittstelle zwischen Pipeline und Excel ist in `docs/DATA_CONTRACT.md` beschrieben, die Übergabe in `docs/UEBERGABE.md`.

## Fehlersuche

| Beobachtung | Ursache | Lösung |
|---|---|---|
| Im Reiter Actions erscheint kein Workflow | Der Ordner `.github` fehlt | Schritt 3 prüfen. Notfalls auf GitHub Add file, Create new file wählen, als Namen `.github/workflows/jao-daily.yml` eintippen und den Inhalt der Datei einfügen (ebenso die anderen Dateien aus `.github/workflows`) |
| Fehler requirements.txt not found | Die Datei fehlt im Hauptverzeichnis | Hochladen |
| Fehler beim Speichern, zum Beispiel permission denied, oder keine Meldung unter Issues | Schreibrechte fehlen | Schritt 4 |
| Fehler 401 oder 403 beim Abruf von JAO | JAO verlangt einen Zugang | Zugangscode bei JAO anfragen und unter Settings, Secrets and variables, Actions als `JAO_API_TOKEN` hinterlegen |
| Fetch JAO: Lauf grün, aber keine neuen Daten, Status waiting | JAO hat den Tag noch nicht veröffentlicht | Nichts tun, der nächste Lauf holt ihn nach |
| Update map geodata rot | Eine Adresse antwortet nicht | Adressen in `config/config.yml`, Abschnitt `sources.geodata`, prüfen. Die alten Dateien bleiben in Benutzung |
| Fetch connection capacity rot, Meldung unter Issues | Ein Netzbetreiber hat Seite oder Datei umgebaut, oder seine Seite weist automatische Abrufe ab (TenneT) | In `config/connection_sources.yml` Adresse, `link_pattern` oder `status_map` der Quelle anpassen. Der letzte gute Stand bleibt im Modell. Lässt sich eine Quelle dauerhaft nicht lesen, dort `enabled: false` setzen |
| Meldung „Network model: new release was not adopted" | Das neue JAO-Netzmodell ist unplausibel oder anders aufgebaut | Text der Meldung lesen. Das bisherige Netzmodell bleibt in Benutzung |
| Tests schlagen fehl | Eine Datei ist beim Hochladen beschädigt oder fehlt | Upload prüfen, Datei neu hochladen |
| Build Excel model bricht beim Schritt Calculate ab | LibreOffice konnte die Datei nicht berechnen | Protokoll lesen. Die Datei ohne gespeicherte Werte lässt sich lokal mit `python scripts/build_excel_model.py` erzeugen |

## Was Sie später anpassen können

* `config/config.yml`: Szenario (`base_case` oder `worst_case`), Schwellen, Netzbetreiber, Adressen der Geodaten. Änderungen am besten über einen Pull Request.
* `config/connection_sources.yml`: weitere Netzbetreiber für die Anschlusskapazität. Ein neuer Block je Veröffentlichung, kein Programmieren nötig, wenn der Netzbetreiber eine Tabelle veröffentlicht.
* `data/manual/substation_aliases.csv`: Schreibvarianten eines Umspannwerks zusammenführen.
* `data/manual/coordinates_manual.csv`: einen Standort von Hand festlegen (geht allen anderen Quellen vor).
* `data/static/grid_expansion_projects.csv`: Netzausbauprojekte. Quelle und Datum je Zeile mitpflegen.
