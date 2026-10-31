# Stolpersteine: was beim Einrichten schiefgehen kann

Für Agenten. Das ist schon einmal passiert. Lies es in Phase 0, damit es bei diesem Besitzer nicht wieder passiert.

| Was passiert ist | Warum | Was der Starter dagegen tut | Was du tust |
|---|---|---|---|
| Zwei Zentralen auf einem Rechner, Einträge landeten mal hier, mal dort | Der Agent hatte vorher eine eigene gebaut, später kam der Starter dazu | `start.py` warnt, wenn schon eine andere läuft; `zentrale_client.py` warnt mit ACHTUNG; `einrichten.py suchen` findet alte | Nie eine zweite neben der ersten benutzen. `docs/EINRICHTEN.md`: alte anhalten, liegen lassen, Einträge nur einzeln nach Ja übernehmen |
| Der Agent hat Seiten der Zentrale „nachgebaut“, sie sahen anders aus als gedacht | Er kannte das Vorbild nicht und hat selbst entworfen | Bilder in `docs/REFERENZ.md` | Den Code der Zentrale nicht umbauen. Sieht etwas anders aus als auf den Bildern: Fassung prüfen, Update holen. Wünsche an die Zentrale als Wunsch notieren und dem Besitzer sagen |
| Nach dem Update sah alles aus wie vorher | `git pull` gemacht, aber die laufende Zentrale nicht neu gestartet | Fassung unten links, ACHTUNG im Client, oranger Hinweis auf der Seite | `py einrichten.py update` (sichert Eigenes, holt, verteilt Regeln, startet neu, prüft die Einträge) |
| Berichte zeigten alle Fragen am Stück, der Besitzer wusste nicht, was er antworten soll | Fragen standen im Text oder alle in einem `--frage` | Die Zentrale teilt mehrere Fragen in einem `--frage` selbst auf; Seite zeigt sie nacheinander | Format aus `AGENTS.md`, „So sieht ein Bericht aus“: je Entscheidung ein `--frage` mit Vorschlägen |
| Beim Update drohten eigene Änderungen am Code verloren zu gehen | Der Agent hatte Seiten selbst umgebaut, das Update überschreibt sie | `update` legt alles Eigene vorher in einen Sicherungszweig und zählt die Einträge | Code der Zentrale nicht selbst ändern; Wünsche als Wunsch. Nach dem Update die Sicherung mit dem Besitzer durchgehen |
| Regeln galten nur in diesem Ordner, in anderen Projekten arbeitete der Agent anders | `REGELN.md` stand nur hier | `regeln_verteilen.py`, ACHTUNG im Client, wenn sie fehlen | Nach jedem Update `py regeln_verteilen.py` (macht `update` von selbst) |
| Platte voll mit `.venv`, `node_modules`, Caches, uv-Versionen | Jedes Projekt legt eigene Umgebungen an, nichts räumt auf | `aufraeumen\putzen.py` und die tägliche Putzrunde (`docs/PUTZEN.md`) | Erst `--probe`, dem Besitzer zeigen, nach Ja `--los` |
| Lange Texte kamen unter PowerShell kaputt an | Anführungszeichen und Umlaute in Befehlen | `--text-datei` bei Berichten, Notizen, Wünschen | Längeres immer erst in eine Datei (UTF-8), dann `--text-datei` |
| Autostart startete nicht | Python aus dem Microsoft Store (Platzhalter unter `WindowsApps`) | Hinweis in `docs/AUTOSTART.md` | Python von python.org nehmen |
| Konsolenfenster blitzten jede Minute auf | Hintergrund-Skripte mit `py` statt `pyw` | Melder und Putzrunde laufen unter `pyw` ohne Fenster | In der Aufgabenplanung immer `pyw.exe` |
| Ein anderes Gerät erreichte die Zentrale nicht | Sie hört standardmäßig nur auf den eigenen Rechner | `start.py --heimnetz`, Firewall-Befehl nur für „Privat“ | `docs/HOMELAB.md`, Schritt 2, nach Ja |
| Agent wollte Passwörter oder Schlüssel in den Chat holen | Bequemer Weg | Schlüssel liegen in Dateien, der Besitzer-Schlüssel wird nur einmal angezeigt | Nie Schlüssel oder Passwörter lesen, schreiben oder wiederholen |
| Auf eine Frage kam keine Antwort, der Agent wartete endlos | Der Besitzer war nicht da | `berichte-warten` endet nach der Wartezeit | Mit dem Rest weitermachen, Stand als Notiz am Wunsch |

Neuer Stolperstein? Nicht hier eintragen (Änderungen in diesem Ordner blockieren das nächste Update), sondern als Notiz
`Anleitungen/Stolpersteine.md` (`notiz-ergaenzen`), und dem Besitzer sagen, damit er es an den weitergibt, der das Repo
pflegt. So hat der nächste Rechner das Problem nicht mehr.
