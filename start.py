#!/usr/bin/env python3
r"""Zentrale starten und Schlüssel verwalten. Braucht nur Python 3.9 oder neuer, sonst nichts.

  py start.py                       Zentrale starten (http://127.0.0.1:8090, nur dieser Rechner)
  py start.py --port 8091           anderer Port
  py start.py agent-neu claude      Schlüssel für einen Agenten anlegen (landet in einer Datei, nicht am Bildschirm)
  py start.py agent-neu codex       … und für den zweiten
  py start.py agenten               alle Schlüssel mit letztem Kontakt
  py start.py agent-weg codex       Schlüssel eines Agenten ungültig machen
  py start.py schluessel-neu        neuer Schlüssel für den Besitzer (der alte gilt dann nicht mehr)
  py start.py --heimnetz            auch für andere Geräte im Heimnetz und über Tailscale (nur mit Schlüssel)
  py start.py geraet-neu "Alter-PC" Schlüssel für ein Gerät im Homelab (darf nur melden), zeigt den Melder-Befehl
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


def geraet_neu(name, port):
    """Schlüssel für ein Gerät: „geraet-<name>“, darf nur melden. Landet als Datei im Schlüssel-Ordner, nicht am Bildschirm."""
    import re
    kurz = re.sub(r"[^a-z0-9-]+", "-", name.strip().lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")).strip("-")[:32]
    if not kurz:
        sys.exit("Der Name braucht Buchstaben oder Ziffern.")
    aid = "geraet-" + kurz
    s = hub.schluessel_neu(aid)
    SCHLUESSEL_ORDNER.mkdir(parents=True, exist_ok=True)
    datei = SCHLUESSEL_ORDNER / f"{aid}.key"
    datei.write_bytes((s + "\n").encode("utf-8"))
    try:
        os.chmod(datei, 0o600)
    except OSError:
        pass
    sys.path.insert(0, str(HIER / "zentrale"))
    import geraete
    hub.PORT = port
    adr = (geraete.adressen() or [f"http://<Tailscale-Adresse dieses Rechners>:{port}"])[0].rstrip("/")
    quelle = "https://raw.githubusercontent.com/hadi-yousef/zentrale-starter/main/melder/melder.py"
    print(f"Schlüssel für das Gerät „{name}“ angelegt: {datei}")
    print("Er darf nur den Zustand melden, sonst nichts. Bring die Datei auf das Gerät (USB-Stick, Netzwerkordner), nicht per Chat.")
    print()
    print("Auf dem Gerät (Python 3.6 oder neuer):")
    print(f"  1. Melder holen:   curl -o melder.py {quelle}")
    print(f"                     (Windows: py -c \"import urllib.request as u; u.urlretrieve('{quelle}', 'melder.py')\"; oder melder{os.sep}melder.py mit auf den Stick)")
    print(f"  2. Einrichten:     python3 melder.py einrichten --zentrale {adr} --name \"{name}\" --schluessel-datei <Pfad zu {datei.name}>")
    print("  3. Autostart:      python3 melder.py autostart      (zeigt die fertigen Befehle für dieses System)")
    print(f"Auf dem Rechner mit der Zentrale selbst: --zentrale http://127.0.0.1:{port}")
    print("Das Gerät braucht Tailscale, die Zentrale muss mit --heimnetz laufen. Ablauf: docs/HOMELAB.md.")


def port_frei(bind, port):
    """Antwortet schon etwas auf dem Port? (Verbinden statt Binden: geht auf allen Systemen gleich.)"""
    try:
        socket.create_connection(("127.0.0.1" if bind in ("0.0.0.0", "") else bind, port), timeout=0.5).close()
        return False
    except OSError:
        return True


def main():
    ap = argparse.ArgumentParser(description="Zentrale starten und Schlüssel verwalten.")
    ap.add_argument("befehl", nargs="?", default="start", choices=["start", "agent-neu", "agenten", "agent-weg", "schluessel-neu", "geraet-neu"])
    ap.add_argument("name", nargs="?", help="Name des Agenten, z. B. claude oder codex")
    ap.add_argument("--port", type=int, default=int(os.environ.get("ZENTRALE_PORT", "8090")))
    ap.add_argument("--bind", default=os.environ.get("ZENTRALE_BIND", "127.0.0.1"),
                    help="Adresse. Standard 127.0.0.1 = nur dieser Rechner. Für andere Geräte: --heimnetz (docs/HOMELAB.md).")
    ap.add_argument("--heimnetz", action="store_true", default=os.environ.get("ZENTRALE_HEIMNETZ") == "1",
                    help="auch für andere Geräte über Tailscale (verschlüsselt, nur mit Schlüssel)")
    ap.add_argument("--lan-unverschluesselt", action="store_true", default=os.environ.get("ZENTRALE_LAN_UNVERSCHLUESSELT") == "1",
                    help="zusätzlich das normale Heimnetz, UNVERSCHLÜSSELT: Schlüssel und Daten sind mitlesbar. "
                         "Nur für Geräte, auf denen Tailscale nicht läuft (docs/HOMELAB.md, Schritt 3)")
    a = ap.parse_args()

    if a.befehl == "geraet-neu":
        if not a.name:
            ap.error("Bitte einen Namen für das Gerät angeben, z. B. MacBook-Air-2015")
        return geraet_neu(a.name, a.port)
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

    if (a.heimnetz or a.lan_unverschluesselt) and a.bind == "127.0.0.1":
        a.bind = "0.0.0.0"
    try:   # läuft schon eine andere Zentrale? Dann nicht still daneben eine zweite (docs/EINRICHTEN.md)
        import einrichten
        andere = [f"127.0.0.1:{p} ({art})" for p, art, _ in einrichten.ports() if art != "diese"]
        if andere:
            print("ACHTUNG: Auf diesem Rechner läuft schon eine andere Zentrale: " + ", ".join(andere) + ". Es darf nur eine geben. "
                  f"Erst `{PY} einrichten.py suchen` und docs/EINRICHTEN.md, nicht beide nebeneinander benutzen.", flush=True)
    except Exception:
        pass
    if not port_frei(a.bind, a.port):
        sys.exit(f"Port {a.port} ist belegt. Läuft die Zentrale schon? Sonst mit --port einen anderen wählen.")
    if not hub.hat_besitzer():
        if OHNE_KONSOLE:   # den Schlüssel nie in die Log-Datei schreiben
            sys.exit(f"Noch kein Schlüssel für den Besitzer. Bitte einmal von Hand starten: {PY} start.py")
        besitzer_zeigen(hub.schluessel_neu(hub.BESITZER), neu=False)
    if a.bind not in ("127.0.0.1", "localhost", "::1"):
        print(f"Die Zentrale nimmt auch andere Geräte über Tailscale an (Adresse {a.bind}). Das normale Heimnetz, fremde Netze und "
              "das Internet weist sie ab, und ohne Schlüssel gibt es keine Daten. Einrichtung: docs/HOMELAB.md, Schritt 2 und 3.")
        if a.lan_unverschluesselt:
            print("ACHTUNG: --lan-unverschluesselt: Sie nimmt auch das normale Heimnetz an, UNVERSCHLÜSSELT. Wer im Netz mitlauscht, "
                  "kann Schlüssel und Daten lesen. Den Schlüssel des Besitzers dort nie eingeben, nur die Tailscale-Adresse nehmen.")
    import app
    print(f"Zentrale läuft: http://{'127.0.0.1' if a.bind == '0.0.0.0' else a.bind}:{a.port}   (beenden mit Strg+C)", flush=True)
    app.starten(a.bind, a.port, lan=a.lan_unverschluesselt)


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
