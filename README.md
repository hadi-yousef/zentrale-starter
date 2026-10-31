# Zentrale Starter

Eine kleine **Zentrale** für einen Rechner, und eine Anleitung, mit der dein KI-Agent (Codex oder Claude Code, z. B. in
T3 Code) bei dir aufräumt: sicher, in kleinen Schritten. Gelöscht wird nur, was sich von selbst neu erzeugt
(Caches, alte Python-Umgebungen, `node_modules`, Temp), alles andere kommt in einen Papierkorb.

![Übersicht der Zentrale](docs/bild-uebersicht.png)

## Was drin ist

| Teil | Was es tut |
|---|---|
| **Zentrale** | Webseite nur auf deinem Rechner: Übersicht, Agenten (wer gerade woran arbeitet, was fertig ist), Papierkorb, Projekte mit Aufgaben, Wünsche mit Priorität und Notizen, Berichte mit Fragen zum Antippen, Notizen als Markdown-Dateien. Hell und dunkel, auf Deutsch. Nur Python, keine weiteren Pakete. |
| **Homelab** | Alte Laptops, Rechner und ein Server: Jedes Gerät meldet über einen kleinen Melder (Windows, Mac, Linux) Prozessor, Speicher, Platten, Akku und Dienste. Seiten Geräte, Dienste, Netzwerk, Speicher mit Warnungen. Dein Agent richtet es mit dir nach `docs/HOMELAB.md` ein, auch Server, Tailscale und nächtliche Sicherung. |
| **Agenten** | Jeder Agent hat einen eigenen Schlüssel und trägt über `zentrale_client.py` ein, was er tut und was er fragen will. |
| **Aufräumen** | Werkzeuge in `aufraeumen\`: Bestandsaufnahme (nur lesen), Sichern auf Stick mit Prüfung, Verschieben nur auf derselben Platte mit Protokoll, Rückgängig für jeden Schritt, Papierkorb statt Löschen. Dazu die Putzrunde gegen Müll, der sich neu erzeugt (uv, pip, npm, alte `.venv` und `node_modules`, Temp). |
| **Anleitung** | `AGENTS.md` (Codex) und `CLAUDE.md` (Claude) führen den Agenten in Phasen durch: Sichern, Bestandsaufnahme, Plan, Aufräumen, Zentrale füllen. Jede Phase endet mit deinem Ja. |
| **Regeln** | `REGELN.md`: wie die Agenten arbeiten sollen. Eine Vorlage, die du anpasst. |

## Schnellstart (Windows)

Du brauchst Python 3.9 oder neuer (python.org, beim Installieren „Add python.exe to PATH“ anhaken).

```powershell
cd $HOME\Projekte
git clone <adresse-dieses-repos> zentrale-starter     # oder ZIP herunterladen und hierher entpacken
cd zentrale-starter
py start.py
```

1. Beim ersten Start erscheint **dein Schlüssel**. Leg ihn in deinen Passwort-Manager. Er wird nur einmal angezeigt.
2. Öffne http://127.0.0.1:8090 und gib den Schlüssel ein.
3. Schlüssel für deine Agenten anlegen (in einem zweiten Fenster):
   ```powershell
   py start.py agent-neu claude
   py start.py agent-neu codex
   ```
   Sie landen in `%USERPROFILE%\.config\zentrale-starter\`. Die Agenten nutzen sie mit `--agent claude` bzw. `--agent codex`.
4. Öffne den Ordner in T3 Code und sag deinem Agenten: **„Lies AGENTS.md und fang mit Phase 0 an.“**
   In Phase 0 trägt er `REGELN.md` mit `py regeln_verteilen.py` in die Anleitung von Claude Code und Codex ein. Dann
   gelten deine Regeln in jedem Projekt: Die Agenten sagen offen, wenn ein Weg falsch ist, und suchen vor dem Bauen
   nach fertigem Open Source.

**Update:** Sag deinem Agenten „Update holen“. Er ruft `py einrichten.py update` auf (holt, verteilt die Regeln,
startet neu, prüft).

**Hattest du schon eine andere Zentrale?** Sag deinem Agenten: **„Richte die Zentrale nach docs/EINRICHTEN.md ein.“**
Er hält die alte an, lässt sie unverändert liegen und fragt dich einzeln, was du daraus mitnehmen willst.

Autostart nach der Anmeldung: `docs\AUTOSTART.md`. **Mac und Linux:** `python3` statt `py`, sonst gleich.

## Sicherheit

- Die Zentrale hört nur auf `127.0.0.1`, also nur auf deinen Rechner. Mit `--heimnetz` (für das Homelab) nimmt sie auch
  Geräte aus dem Heimnetz und über Tailscale an, weist fremde Netze ab und gibt ohne Schlüssel keine Daten heraus.
- Geräte haben eigene Schlüssel, die nur melden dürfen.
- Schlüssel werden nur als Prüfsumme gespeichert. `daten\` (deine Einträge) und das Aufräum-Protokoll stehen in `.gitignore`.
- Die Aufräum-Werkzeuge verschieben auf derselben Platte in einen Papierkorb und schreiben jeden Schritt ins Protokoll.
  Nur die Putzrunde (`aufraeumen\putzen.py`) entfernt endgültig, und nur, was sich von selbst neu erzeugt
  (`docs/PUTZEN.md`): erst als Probe, dann nach deinem Ja.

## Lizenz

MIT, siehe `LICENSE`. Die Symbole sind von [Lucide](https://lucide.dev) (ISC-Lizenz, siehe `zentrale\vendor\lucide-icons\LICENSE`).
