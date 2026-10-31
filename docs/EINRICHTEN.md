# Zentrale einrichten, getrennt von einer alten

Für Agenten. Du nimmst den Besitzer an die Hand: **Du machst jeden Schritt selbst**, er muss nur seinen Schlüssel eingeben
und mit Ja oder Nein antworten. Schick ihm keine Befehle zum Abtippen.

Gibt es auf dem Rechner schon eine andere Zentrale (älterer Ordner, eigene Bastelei, anderer Port), dann gilt:
**Die alte wird angehalten und bleibt unverändert liegen.** Die neue bekommt eigenen Ordner, eigene Daten, eigene
Schlüssel und den Autostart. Aus der alten kommt nichts von selbst herüber, nur was der Besitzer einzeln mit Ja auswählt.

Nie: in den alten Ordner schreiben, ihn verschieben oder löschen, Datendateien (`.json`) von alt nach neu kopieren,
beide Zentralen gleichzeitig laufen lassen.

| Schritt | Was | Ändert etwas? |
|---|---|---|
| 1 | Suchen: Welche Zentralen gibt es? | nein |
| 2 | Die alte anhalten | ja, nach Ja; rückgängig machbar |
| 3 | Die neue starten, Schlüssel anlegen | nur im neuen Ordner |
| 4 | Prüfen: alles getrennt? | nein |
| 5 | Einträge aus der alten übernehmen | nur in der neuen, je Eintrag nach Ja |
| 6 | Autostart der neuen | nach Ja |
| 7 | Abschluss: Übergabe-Notiz, Rundgang | nur Notiz |

Sag dem Besitzer am Anfang in zwei Sätzen, was passiert: „Ich richte deine neue Zentrale ein. Die alte halte ich nur an,
sie bleibt unverändert liegen, und du entscheidest einzeln, was du daraus mitnehmen willst.“

## 1. Suchen (nichts ändern)

```powershell
cd $HOME\Projekte\zentrale-starter
py einrichten.py suchen
```

Es zeigt: Was auf den Ports antwortet, welche Programme laufen, welcher Autostart eingerichtet ist, Ordner mit einer
anderen Zentrale, Schlüsselordner, Umgebungsvariablen, und Zeilen in den Anleitungen der Agenten, die auf eine andere
Zentrale zeigen. Zeig das dem Besitzer als Tabelle (Was, Wo, gehört zu: alt oder neu).

- **Nichts gefunden:** weiter mit Schritt 3.
- **Der alte Ordner ist dieser Ordner** (ein älterer Stand dieses Repos, `git remote -v` zeigt dieselbe Adresse):
  Dann ist es keine fremde Zentrale, sondern ein Update. Nach `AGENTS.md`, „Update einspielen“, und danach Schritt 4.
- **Der Ordner `$HOME\Projekte\zentrale-starter` ist von etwas anderem belegt:** Frag den Besitzer nach einem neuen Namen
  (Vorschlag `Zentrale`) und klone das Repo dorthin. Den belegten Ordner nicht anfassen.

## 2. Die alte anhalten (nach Ja)

Frage: „Darf ich die alte Zentrale anhalten? Sie bleibt mit allen Daten liegen.“ Erst nach Ja:

1. **Programme beenden**, nur die mit „ANDERE“ aus Schritt 1: `Stop-Process -Id <PID>`.
2. **Autostart abschalten, nicht löschen:** `Disable-ScheduledTask -TaskName "<Name>"`. Rückgängig:
   `Enable-ScheduledTask -TaskName "<Name>"`.
3. **Alte Agenten-Schlüssel beiseitelegen**, falls die alte denselben Schlüsselordner benutzt hat
   (`%USERPROFILE%\.config\zentrale-starter` mit Schlüsseln, bevor die neue lief):
   `Rename-Item $HOME\.config\zentrale-starter zentrale-starter-alt`. Ein anderer Schlüsselordner bleibt, wie er ist.
4. **Umgebungsvariablen**, die auf die alte zeigen (`ZENTRALE_DATEN`, `ZENTRALE_URL`, …): alten Wert in die Übergabe-Notiz
   schreiben, dann `[Environment]::SetEnvironmentVariable("ZENTRALE_DATEN", $null, "User")`. Danach neues PowerShell-Fenster.
5. **Anleitungen der Agenten**, die auf die alte zeigen (Schritt 1, Punkt 7): dem Besitzer die Zeile zeigen und nach Ja
   auf die neue Zentrale ändern (`http://127.0.0.1:8090`, der neue Ordner). Vorher eine Kopie der Datei daneben legen.
6. Noch einmal `py einrichten.py suchen`: Ports und Programme zeigen jetzt nur noch „diese“ oder nichts.

## 3. Die neue starten

```powershell
cd $HOME\Projekte\zentrale-starter
git pull                       # neueste Fassung
py start.py                    # in T3 Code als eigener Hintergrund-Befehl
```

- Beim ersten Start erscheint der **Schlüssel des Besitzers**. Den liest nur er. Du schreibst ihn nirgends hin und
  wiederholst ihn nicht. Bitte ihn, ihn in seinen Passwort-Manager zu legen, http://127.0.0.1:8090 zu öffnen, den
  Schlüssel einzugeben und ein Lesezeichen zu setzen. Alte Lesezeichen auf andere Adressen führen jetzt ins Leere.
- Schlüssel für die Agenten: `py start.py agent-neu claude` und `py start.py agent-neu codex`.
- Regeln in alle Projekte: `py regeln_verteilen.py`. Hook für Claude nach OK: `py hooks\einrichten.py`.
- Ab jetzt den Auftrag als Wunsch eintragen: `py zentrale_client.py --agent claude wunsch "Neue Zentrale einrichten" --prio hoch`
  und den Stand nach jedem Schritt als Notiz.

## 4. Prüfen

```powershell
py einrichten.py pruefen
```

Muss enden mit „Alles getrennt“. Sonst steht da, was noch vermischt ist, und wie es weggeht. Danach die Seite mit den
Bildern in `docs/REFERENZ.md` vergleichen: links „Agenten“ und „Papierkorb“, unten links dieselbe Fassung wie in
`zentrale\hub.py`.

## 5. Einträge aus der alten übernehmen (je Eintrag nach Ja)

```powershell
py einrichten.py alt-zeigen <alter Ordner>
```

Es liest die alte Zentrale nur und zeigt offene Wünsche, Projekte, offene Aufgaben und Notizen. Zeig dem Besitzer die Liste
nummeriert und frag: „Welche davon willst du in der neuen Zentrale haben? Zum Beispiel ‚1, 3, 4‘ oder ‚keine‘.“
Ist er nicht im Chat, als Bericht, je Gruppe (Wünsche, Projekte, Notizen) eine Frage.

Übernehmen nur mit den Befehlen der neuen Zentrale, nie durch Kopieren von Dateien:

| Aus der alten | In die neue |
|---|---|
| Wunsch | `wunsch "Titel" --text "…" --prio hoch` (Priorität wie in der alten, sonst fragen), Stand als `wunsch-notiz` |
| Projekt | `projekt-neu "Name" --beschreibung "…" --ort "PC:C:\…" --schritt "…"` |
| Aufgabe | `aufgabe "…" --projekt <Name> --fuer besitzer` |
| Notiz | Text lesen, dann `notiz-neu "Titel" --ordner <passender fester Ordner> --text-datei <datei>` |

Hat die alte ein anderes Format (keine `wuensche.json`, `pos.json` oder `notizen`): die Dateien lesen und dem Besitzer
die Einträge genauso als Liste zeigen. Was du nicht sicher zuordnen kannst, fragst du.

## 6. Autostart der neuen (nach Ja)

Nach `docs/AUTOSTART.md`. Danach `py einrichten.py pruefen`: Der Autostart der alten ist aus, nur der neue läuft.

## 7. Abschluss

- Übergabe-Notiz `Übergaben/<JJJJ-MM-TT>.md`: wo die alte liegt, was angehalten wurde (Programme, Autostart mit
  Rückgängig-Befehl, Schlüsselordner, Umgebungsvariablen mit altem Wert), was übernommen wurde, was nicht.
- Kurzer Rundgang mit dem Besitzer: Übersicht, Berichte, Wünsche, Projekte, Notizen, Papierkorb.
- Wunsch „Neue Zentrale einrichten“ abhaken (`wunsch-erledigt <nr> --ergebnis "…"`).
- Der alte Ordner bleibt liegen. Weg kommt er nur, wenn der Besitzer es ausdrücklich sagt, und dann mit
  `aufraeumen\verschieben.py --papierkorb`, nie gelöscht.

## Rückgängig

| Was | Befehl |
|---|---|
| Autostart der alten wieder an | `Enable-ScheduledTask -TaskName "<Name>"` |
| Alte Schlüssel zurück | neuen Ordner umbenennen, dann `Rename-Item $HOME\.config\zentrale-starter-alt zentrale-starter` |
| Umgebungsvariable zurück | `[Environment]::SetEnvironmentVariable("<Name>", "<alter Wert>", "User")` |
| Alte Zentrale starten | neue beenden (gleicher Port), dann wie früher starten |
