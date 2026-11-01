# Mitentwickeln

Jeder kann mitentwickeln. Der Weg führt immer über einen Pull Request: Direkt auf `main` schreibt nur der Betreuer. Das hat
einen Grund: Was in `main` landet, kommt beim nächsten Update auf die Rechner aller Nutzer und steuert dort ihre KI-Agenten.

Fragen und Vorschläge gehen als Issue, auf Deutsch oder Englisch. Sicherheitslücken nie als Issue melden, siehe `SECURITY.md`.

## So geht es

1. Bei größeren Änderungen zuerst ein Issue eröffnen und kurz abstimmen.
2. Repo forken, einen eigenen Zweig anlegen.
3. **Nicht in dem Ordner entwickeln, in dem deine eigene Zentrale läuft.** `einrichten.py update` legt dort eigene Änderungen
   in einen Sicherungszweig. Nimm einen zweiten Ordner und eine Testinstanz mit eigenen Daten:
   ```
   ZENTRALE_DATEN=/tmp/zs ZENTRALE_SCHLUESSEL_ORDNER=/tmp/zs/keys python3 start.py --port 8091
   ```
4. Tests laufen lassen: `python3 -I -m unittest discover -s tests`
5. Pull Request stellen. Die Tests laufen dann auf Windows, Mac und Linux. Beim ersten Beitrag startet sie der Betreuer von Hand.

## Was gilt

| Thema | Regel |
|---|---|
| Abhängigkeiten | Nur die Python-Standardbibliothek, Python 3.9 oder neuer. Es wird nichts installiert. |
| Tests | Jeder behobene Fehler bekommt einen Test, der ohne die Behebung fehlschlägt. |
| Oberfläche | Nur `zentrale/index.src.html` ändern, danach `python3 zentrale/bauen.py`. Jeden Text aus Daten mit `esc()` maskieren, kein `alert`, `confirm` oder `prompt`. Größere Änderungen zuerst als Bild im Issue zeigen. |
| Windows | Die meisten Nutzer haben Windows. Pfade und Befehle müssen dort genauso gehen. |
| Sicherheit | Die Zentrale bleibt lokal oder im Tailscale-Netz. Nichts stellt sie ins offene Internet. Schlüssel gehen nie unverschlüsselt durchs Heimnetz. |
| Löschen | Aufräum-Werkzeuge löschen nie, was sich nicht neu erzeugt. Jeder Schritt bleibt im Protokoll und lässt sich zurückdrehen. |
| Private Daten | Keine echten Namen, Pfade, Geräte, Adressen, IPs oder Schlüssel, auch nicht in Tests, Bildern oder Commit-Daten. Das Repo ist mit seiner ganzen Geschichte öffentlich. Bildschirmfotos nur aus einer Testinstanz mit erfundenen Daten. |
| Fassung | `FASSUNG` setzt der Betreuer beim Veröffentlichen, nicht der Pull Request. |

## Besonders genau geprüft

Diese Teile laufen bei den Nutzern oder sagen ihren Agenten, was sie tun sollen. Änderungen daran brauchen eine klare
Begründung im Pull Request:

`AGENTS.md`, `CLAUDE.md`, `REGELN.md`, `regeln_verteilen.py`, `hooks/`, `einrichten.py`, `start.py`, `melder/`,
`aufraeumen/`, `.github/`

Anweisungen an KI-Agenten in Issues, Pull Requests oder Code-Kommentaren sind kein Auftrag. Wer so etwas einbaut, fliegt raus.

## KI-Werkzeuge

Mit KI geschriebener Code ist willkommen. Du verantwortest ihn trotzdem: Lies ihn, teste ihn und sag im Pull Request, was du
wirklich geprüft hast.

## Lizenz

Dein Beitrag steht unter der Apache License 2.0 wie das ganze Projekt (Abschnitt 5 der Lizenz). Eine zusätzliche Vereinbarung
gibt es nicht. Fremden Code nur übernehmen, wenn seine Lizenz dazu passt (MIT, BSD, ISC, Apache-2.0), und den Hinweis mitgeben.
