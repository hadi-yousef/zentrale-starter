# Seite „Agenten“: wer gerade woran arbeitet

Für Agenten (Codex und Claude Code). Der Besitzer sieht in der Zentrale unter **Agenten** eine Karte je Agent:
„arbeitet“ (grün), „still“ (orange, seit 30 Minuten keine Meldung) oder „Pause“. Auf der Karte stehen die Arbeit, die
Wunsch-Nummer, seit wann, der letzte Schritt mit Balken und was zuletzt fertig wurde. Darunter steht die Liste
„Fertig gemeldet“. Antippen öffnet die Einzelheiten.

Eine Arbeit heißt hier **Lauf**: Start, Zwischenstände, Fertig.

## Claude Code: meldet sich von selbst (Hook)

`hooks/claude_lauf.py` läuft bei jeder Nachricht des Besitzers (Start) und wenn Claude fertig ist (Fertig).
Titel ist die erste Zeile seiner Nachricht. Steht darin „Wunsch Nr. 7“, hängt der Lauf an Wunsch Nr. 7.
Kurze Antworten unter 20 Sekunden landen nicht in „Fertig gemeldet“.

Einrichten, einmal (nach OK des Besitzers, es ändert die Einstellungen von Claude Code):

```powershell
cd $HOME\Projekte\zentrale-starter
py hooks\einrichten.py
```

Es legt vorher eine Kopie von `%USERPROFILE%\.claude\settings.json` daneben und lässt andere Einstellungen in Ruhe.
Danach T3 Code einmal neu starten. Austragen: `py hooks\einrichten.py --weg`.

Prüfen: Dem Besitzer sagen, er soll Claude etwas fragen. Auf der Seite „Agenten“ steht Claude dann auf „arbeitet“.
Oder: `py zentrale_client.py --agent codex laeufe`.

## Codex: meldet sich selbst mit Befehlen

Für Codex gibt es hier keinen Hook. Deshalb gilt: **Jede Arbeit, die länger als ein paar Minuten dauert, meldest du.**

| Wann | Befehl (nach `py zentrale_client.py --agent codex`) |
|---|---|
| Du fängst an | `lauf start "Downloads aufräumen" --wunsch 7` |
| Nach jedem größeren Block | `lauf stand "Block 2 von 5 verschoben" --fortschritt 40` |
| Fertig | `lauf fertig "412 Dateien im Papierkorb, Protokoll liegt bei"` |
| Schiefgegangen | `lauf fertig "Platte D: nicht erreichbar" --fehler` |
| Nachsehen | `laeufe` |

- Titel wie beim Wunsch: aus Sicht des Besitzers, kurz. `--wunsch` immer angeben, wenn es einen gibt.
- Zwei Arbeiten gleichzeitig: jeder eine eigene Kennung geben, `--lauf fotos` bei allen drei Befehlen.
- Ein Lauf ersetzt nicht die Stand-Notiz am Wunsch (`docs/WUENSCHE.md`). Der Lauf zeigt **jetzt**, die Notiz hält den
  Stand **für später** fest. Fertig heißt: `lauf fertig` und, wenn der Wunsch erledigt ist, `wunsch-erledigt`.
- Vergessen zu melden: Nach 6 Stunden ohne Meldung legt die Zentrale den Lauf als „abgebrochen“ ab.

## Nach einem Update einspielen

Siehe `AGENTS.md`, Abschnitt „Update einspielen“ (git pull, Zentrale neu starten, prüfen). Danach den Hook für Claude
einrichten (siehe oben), nach OK des Besitzers.
