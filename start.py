#!/usr/bin/env python3
r"""Zentrale starten und Schlüssel verwalten. Braucht nur Python 3.9 oder neuer, sonst nichts.

  py start.py                       Zentrale starten (http://127.0.0.1:8090, nur dieser Rechner)
  py start.py --port 8091           anderer Port
  py start.py agent-neu claude      Schlüssel für einen Agenten anlegen (landet in einer Datei, nicht am Bildschirm)
  py start.py agent-neu codex       … und für den zweiten
  py start.py agenten               alle Schlüssel mit letztem Kontakt
  py start.py agent-weg codex       Schlüssel eines Agenten ungültig machen
  py start.py schluessel-neu        neuer Schlüssel für den Besitzer (der alte gilt dann nicht mehr)
  (Mac und Linux: python3 statt py)

Beim ersten Start wird der Schlüssel des Besitzers erzeugt und EINMAL angezeigt. Er wird nur als Prüfsumme gespeichert.
Daten liegen in .\daten (oder ZENTRALE_DATEN). Agenten-Schlüssel liegen in %USERPROFILE%\.config\zentrale-starter\<agent>.key
(Mac und Linux: ~/.config/zentrale-starter/, oder ZENTRALE_SCHLUESSEL_ORDNER).
Ohne Konsolenfenster (pythonw/pyw, Autostart) schreibt die Zentrale ihre Meldungen nach daten\zentrale.log.
"""
import argparse
import os
import socket
import sys
import time
from pathlib import Path

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER / "zentrale"))
os.environ.setdefault("ZENTRALE_DATEN", str(HIER / "daten"))
try:
    sys.stdout.reconfigure(errors="replace")
except (AttributeError, ValueError):
    pass

import hub  # noqa: E402  (braucht ZENTRALE_DATEN)

PY = "py" if os.name == "nt" else "python3"
OHNE_KONSOLE = sys.stdout is None   # gestartet mit pythonw/pyw, z. B. aus der Aufgabenplanung
if OHNE_KONSOLE:
    hub.STATE_DIR.mkdir(parents=True, exist_ok=True)
    sys.stdout = sys.stderr = open(hub.STATE_DIR / "zentrale.log", "a", encoding="utf-8", buffering=1)
SCHLUESSEL_ORDNER = Path(os.environ.get("ZENTRALE_SCHLUESSEL_ORDNER") or Path.home() / ".config" / "zentrale-starter")


def besitzer_zeigen(s, neu=True):
    print()
    print("=" * 64)
    print(" Schlüssel des Besitzers" + (" (neu)" if neu else ""))
    print()
    print("   " + s)
    print()
    print(" Er wird nur jetzt angezeigt. Bewahre ihn im Passwort-Manager auf.")
    print(" Die Oberfläche fragt einmal danach und merkt ihn sich im Browser.")
    print(f" Verloren? `{PY} start.py schluessel-neu` macht einen neuen.")
    print("=" * 64)
    print()


def agent_neu(aid):
    s = hub.schluessel_neu(aid)
    SCHLUESSEL_ORDNER.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(SCHLUESSEL_ORDNER, 0o700)   # Mac und Linux; unter Windows schützt das Benutzerprofil
    except OSError:
        pass
    datei = SCHLUESSEL_ORDNER / f"{aid}.key"
    datei.write_bytes((s + "\n").encode("utf-8"))
    try:
        os.chmod(datei, 0o600)
    except OSError:
        pass
    print(f"Schlüssel für „{aid}“ angelegt: {datei}")
    print(f"Der Agent nutzt ihn so: {PY} zentrale_client.py --agent {aid} wuensche")


def port_frei(bind, port):
    """Antwortet schon etwas auf dem Port? (Verbinden statt Binden: geht auf allen Systemen gleich.)"""
    try:
        socket.create_connection(("127.0.0.1" if bind in ("0.0.0.0", "") else bind, port), timeout=0.5).close()
        return False
    except OSError:
        return True


def main():
    ap = argparse.ArgumentParser(description="Zentrale starten und Schlüssel verwalten.")
    ap.add_argument("befehl", nargs="?", default="start", choices=["start", "agent-neu", "agenten", "agent-weg", "schluessel-neu"])
    ap.add_argument("name", nargs="?", help="Name des Agenten, z. B. claude oder codex")
    ap.add_argument("--port", type=int, default=int(os.environ.get("ZENTRALE_PORT", "8090")))
    ap.add_argument("--bind", default=os.environ.get("ZENTRALE_BIND", "127.0.0.1"),
                    help="Adresse. Standard 127.0.0.1 = nur dieser Rechner. Andere Geräte erst mit Phase 6 (siehe AGENTS.md).")
    a = ap.parse_args()

    if a.befehl == "agent-neu":
        if not a.name or a.name == hub.BESITZER:
            ap.error("Bitte einen Namen für den Agenten angeben, z. B. claude")
        return agent_neu(a.name)
    if a.befehl == "agent-weg":
        if not a.name or a.name == hub.BESITZER:
            ap.error("Bitte den Namen des Agenten angeben.")
        hub.schluessel_weg(a.name)
        return print(f"Schlüssel von „{a.name}“ gilt nicht mehr. Die Datei im Schlüssel-Ordner kannst du in den Papierkorb legen.")
    if a.befehl == "agenten":
        for x in hub.agenten()["agenten"]:
            zuletzt = time.strftime("%d.%m.%Y %H:%M", time.localtime(x["zuletzt"])) if x["zuletzt"] else "noch nie"
            print(f"{x['id']:<20} zuletzt: {zuletzt}")
        return
    if a.befehl == "schluessel-neu":
        return besitzer_zeigen(hub.schluessel_neu(hub.BESITZER))

    if not port_frei(a.bind, a.port):
        sys.exit(f"Port {a.port} ist belegt. Läuft die Zentrale schon? Sonst mit --port einen anderen wählen.")
    if not hub.hat_besitzer():
        if OHNE_KONSOLE:   # den Schlüssel nie in die Log-Datei schreiben
            sys.exit(f"Noch kein Schlüssel für den Besitzer. Bitte einmal von Hand starten: {PY} start.py")
        besitzer_zeigen(hub.schluessel_neu(hub.BESITZER), neu=False)
    if a.bind not in ("127.0.0.1", "localhost", "::1"):
        print(f"Achtung: Die Zentrale hört auf {a.bind}, also auch auf andere Geräte im Netz. Nur in einem vertrauten Netz tun.")
    import app
    print(f"Zentrale läuft: http://{'127.0.0.1' if a.bind == '0.0.0.0' else a.bind}:{a.port}   (beenden mit Strg+C)", flush=True)
    app.starten(a.bind, a.port)


if __name__ == "__main__":
    # Windows: bei Weiterleitung (Agenten lesen die Ausgabe) nimmt Python sonst cp1252, und „→“ oder Umlaute brechen ab
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    try:
        main()
    except ValueError as e:
        sys.exit(f"Fehler: {e}")
