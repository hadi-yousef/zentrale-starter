#!/usr/bin/env python3
"""Schreibt REGELN.md in die Anleitungen von Claude Code und Codex, damit die Regeln in **jedem** Projekt gelten,
nicht nur in diesem Ordner. Dazu legt es den Recherche-Agenten für Claude Code an (vorlagen/claude-agents/recherche.md).

Aufruf: py regeln_verteilen.py             (Mac/Linux: python3)
        py regeln_verteilen.py --pruefen   nur zeigen, was veraltet ist
        py regeln_verteilen.py --weg       die Regeln wieder austragen (der Recherche-Agent bleibt)

Ziele: %USERPROFILE%\\.claude\\CLAUDE.md und %USERPROFILE%\\.codex\\AGENTS.md (Mac/Linux: ~/.claude, ~/.codex).
Die Regeln stehen dort zwischen <!-- REGELN:ANFANG --> und <!-- REGELN:ENDE -->. Was außerhalb steht, bleibt, wie es ist.
Vor der ersten Änderung einer Datei wird eine Kopie daneben gelegt (…vor-zentrale-<zeit>). Zweimal aufrufen schadet nicht.
Nach jeder Änderung an REGELN.md und nach jedem `git pull` noch einmal aufrufen. Danach neue Threads starten.
"""
import os
import re
import shutil
import sys
import time
from pathlib import Path

ORDNER = Path(__file__).resolve().parent
ANFANG, ENDE = "<!-- REGELN:ANFANG -->", "<!-- REGELN:ENDE -->"
PY = "py" if os.name == "nt" else "python3"
RECHERCHE = ORDNER / "vorlagen" / "claude-agents" / "recherche.md"
KENNUNG = "zentrale-starter"   # steht im Recherche-Agenten; fremde Agenten gleichen Namens bleiben unangetastet


def ziele():
    codex = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    return [Path.home() / ".claude" / "CLAUDE.md", codex / "AGENTS.md"]


def block():
    t = (ORDNER / "REGELN.md").read_text(encoding="utf-8-sig").strip()
    t = re.sub(r"^# .*\n+", "", t)                    # Titel weg, dafür eigene Überschrift
    t = re.sub(r"^## ", "### ", t, flags=re.M)        # eine Stufe tiefer
    client = ORDNER / "zentrale_client.py"
    kopf = (f"## Regeln des Besitzers (aus `REGELN.md` in `{ORDNER}`, hier nicht ändern)\n\n"
            f"Sie gelten in jedem Projekt. Neu schreiben: `{PY} \"{ORDNER / 'regeln_verteilen.py'}\"`.\n"
            f"- Die Zentrale: `{PY} \"{client}\" --agent <claude|codex> <befehl>` (Wünsche, Berichte, Notizen). "
            f"Anleitung: `{ORDNER / 'AGENTS.md'}`.\n"
            f"- Pfade in den Regeln (`docs\\…`, `aufraeumen\\…`, `zentrale_client.py`) liegen in `{ORDNER}`.\n")
    return f"{ANFANG}\n{kopf}\n{t}\n{ENDE}"


def neuer_text(alt, b, weg=False):
    """Text der Anleitung nach dem Eintragen (oder Austragen) des Regel-Blocks."""
    a, e = alt.find(ANFANG), alt.find(ENDE)
    if a >= 0 and e > a:
        vorher, nachher = alt[:a], alt[e + len(ENDE):]
        if weg:
            return (vorher.rstrip() + "\n" + nachher.lstrip()).strip() + "\n" if (vorher + nachher).strip() else ""
        return vorher + b + nachher
    if weg:
        return alt
    return (alt.rstrip() + "\n\n" + b + "\n") if alt.strip() else b + "\n"


def veraltet():
    """Liste der Anleitungen, in denen die Regeln fehlen oder alt sind (für die ACHTUNG-Zeile im Client)."""
    try:
        b = block()
    except OSError:
        return []
    raus = []
    for p in ziele():
        try:
            s = p.read_text(encoding="utf-8-sig") if p.exists() else ""
        except OSError:
            continue
        if neuer_text(s, b) != s:
            raus.append(p)
    return raus


def recherche_agent(pruefen, weg):
    ziel = Path.home() / ".claude" / "agents" / "recherche.md"
    if not RECHERCHE.exists():
        return False
    neu = RECHERCHE.read_text(encoding="utf-8")
    alt = ziel.read_text(encoding="utf-8-sig") if ziel.exists() else None
    if alt is not None and KENNUNG not in alt:
        print(f"bleibt:   {ziel} (ein eigener Agent gleichen Namens, nicht von hier)")
        return False
    if weg:   # nicht löschen (REGELN.md); wer ihn nicht will, verschiebt ihn in den Papierkorb
        if alt is not None:
            print(f"bleibt:   {ziel} (wer ihn nicht will: mit aufraeumen\\verschieben.py --papierkorb wegräumen)")
        return False
    if alt == neu:
        print(f"aktuell:  {ziel}")
        return False
    if not pruefen:
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_text(neu, encoding="utf-8")
    print(("veraltet: " if pruefen else "neu:      ") + str(ziel))
    return True


def main():
    pruefen, weg = "--pruefen" in sys.argv, "--weg" in sys.argv
    b, alt_gefunden = block(), False
    for p in ziele():
        s = p.read_text(encoding="utf-8-sig") if p.exists() else ""
        n = neuer_text(s, b, weg)
        if n == s:
            print(f"aktuell:  {p}" if not weg else f"nichts:   {p}")
            continue
        alt_gefunden = True
        if pruefen:
            print(f"veraltet: {p}")
            continue
        if p.exists() and ANFANG not in s:   # erste Änderung: Stand davor daneben legen
            kopie = p.with_name(f"{p.name}.vor-zentrale-{time.strftime('%Y%m%d-%H%M%S')}")
            if not kopie.exists():
                shutil.copy2(p, kopie)
                print(f"Kopie:    {kopie}")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(n, encoding="utf-8")
        print(("ausgetragen: " if weg else "neu:      ") + str(p))
    if recherche_agent(pruefen, weg):
        alt_gefunden = True
    if not pruefen and alt_gefunden:
        print("Fertig. Neue Threads in T3 Code lesen die Regeln; laufende Threads kennen sie erst nach einem Neustart.")
    sys.exit(1 if pruefen and alt_gefunden else 0)


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):   # Windows: sonst cp1252, Umlaute brechen ab
        try:
            _s.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    main()
