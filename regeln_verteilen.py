#!/usr/bin/env python3
"""Schreibt REGELN.md und die eigenen Regeln aus REGELN.lokal.md in die Anleitungen von Claude Code und Codex, damit sie
in **jedem** Projekt gelten, nicht nur in diesem Ordner. Dazu legt es den Recherche-Agenten für Claude Code an
(vorlagen/claude-agents/recherche.md).

REGELN.md ist die Vorlage und kommt mit jedem Update neu. Eigene Regeln gehören nach REGELN.lokal.md: Die Datei steht nicht in
Git, kein Update fasst sie an, und sie geht der Vorlage vor. Hat jemand REGELN.md selbst geändert, holt dieses Skript die
eigenen Zeilen nach dem Update aus dem Sicherungszweig dorthin.

Aufruf: py regeln_verteilen.py             (Mac/Linux: python3)
        py regeln_verteilen.py --pruefen   nur zeigen, was veraltet ist
        py regeln_verteilen.py --weg       die Regeln wieder austragen (der Recherche-Agent bleibt)
        py regeln_verteilen.py --ziel <datei>   zusätzliche Anleitung, wird gemerkt (REGELN.ziele.txt)

Ziele: %USERPROFILE%\\.claude\\CLAUDE.md und %USERPROFILE%\\.codex\\AGENTS.md (Mac/Linux: ~/.claude, ~/.codex), dazu die
Ordner aus CLAUDE_CONFIG_DIR und CODEX_HOME, wenn sie gesetzt sind, und alles aus REGELN.ziele.txt.
Die Regeln stehen dort zwischen <!-- REGELN:ANFANG --> und <!-- REGELN:ENDE -->. Was außerhalb steht, bleibt, wie es ist.
Vor der ersten Änderung einer Datei wird eine Kopie daneben gelegt (…vor-zentrale-<zeit>). Zweimal aufrufen schadet nicht.
Nach jeder Änderung an REGELN.md und nach jedem `git pull` noch einmal aufrufen. Danach neue Threads starten.
"""
import difflib
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ORDNER = Path(__file__).resolve().parent
ANFANG, ENDE = "<!-- REGELN:ANFANG -->", "<!-- REGELN:ENDE -->"
PY = "py" if os.name == "nt" else "python3"
RECHERCHE = ORDNER / "vorlagen" / "claude-agents" / "recherche.md"
KENNUNG = "zentrale-starter"   # steht im Recherche-Agenten; fremde Agenten gleichen Namens bleiben unangetastet
LOKAL = ORDNER / "REGELN.lokal.md"          # eigene Regeln, nicht in Git
ZIELE_DATEI = ORDNER / "REGELN.ziele.txt"   # zusätzliche Anleitungen (--ziel), nicht in Git


def ziele():
    raus = [Path.home() / ".claude" / "CLAUDE.md", Path.home() / ".codex" / "AGENTS.md"]
    if os.environ.get("CLAUDE_CONFIG_DIR"):
        raus.append(Path(os.environ["CLAUDE_CONFIG_DIR"]) / "CLAUDE.md")
    if os.environ.get("CODEX_HOME"):
        raus.append(Path(os.environ["CODEX_HOME"]) / "AGENTS.md")
    try:
        raus += [Path(z.strip()) for z in ZIELE_DATEI.read_text(encoding="utf-8-sig").splitlines() if z.strip()]
    except OSError:
        pass
    gesehen, eindeutig = set(), []
    for p in raus:
        k = os.path.normcase(os.path.abspath(p))
        if k not in gesehen:
            gesehen.add(k)
            eindeutig.append(p)
    return eindeutig


def ziel_merken(pfad):
    """--ziel: zusätzliche Anleitung (eine Datei, kein Ordner) für alle weiteren Läufe merken."""
    p = Path(pfad).expanduser().resolve()
    if p.is_dir():
        sys.exit(f"--ziel braucht eine Datei, kein Ordner: {p}\\AGENTS.md oder {p}\\CLAUDE.md")
    # Umgebungsvariablen zählen hier nicht: Sie gelten nur für diesen Aufruf, ein anderer Agent hat sie vielleicht nicht
    fest = [Path.home() / ".claude" / "CLAUDE.md", Path.home() / ".codex" / "AGENTS.md"]
    try:
        fest += [Path(z.strip()) for z in ZIELE_DATEI.read_text(encoding="utf-8-sig").splitlines() if z.strip()]
    except OSError:
        pass
    if not any(os.path.normcase(os.path.abspath(x)) == os.path.normcase(str(p)) for x in fest):
        with ZIELE_DATEI.open("a", encoding="utf-8") as f:
            f.write(f"{p}\n")
        print(f"gemerkt:  {p}")


def _git(*a):
    return subprocess.run(["git", "-C", str(ORDNER), *a], capture_output=True, text=True, encoding="utf-8", errors="replace")


def eigene_uebernehmen():
    """Eigene Änderungen an REGELN.md aus dem neuesten Sicherungszweig nach REGELN.lokal.md holen, jeden Zweig nur einmal."""
    if not (ORDNER / ".git").exists():
        return
    zweige = _git("for-each-ref", "--sort=-refname", "--format=%(refname:short)", "refs/heads/sicherung-vor-update-*").stdout.split()
    if not zweige or _git("config", "--get", "zentrale.regelnUebernommen").stdout.strip() == zweige[0]:
        return
    zweig = zweige[0]
    eigen = _git("show", f"{zweig}:REGELN.md")
    vorlagen = []
    for c in _git("log", "--format=%H", "HEAD", "--", "REGELN.md").stdout.split():
        v = _git("show", f"{c}:REGELN.md")
        if v.returncode == 0:
            vorlagen.append(v.stdout.splitlines())
    neu, weg = [], []
    if eigen.returncode == 0 and vorlagen and eigen.stdout.splitlines() not in vorlagen:
        e = eigen.stdout.splitlines()
        v = max(vorlagen, key=lambda x: difflib.SequenceMatcher(None, x, e, autojunk=False).ratio())
        schon = set(LOKAL.read_text(encoding="utf-8-sig").splitlines()) if LOKAL.exists() else set()
        kopf = ""
        for art, i1, i2, j1, j2 in difflib.SequenceMatcher(None, v, e, autojunk=False).get_opcodes():
            weg += [z for z in v[i1:i2] if z.strip()] if art in ("replace", "delete") else []
            if art not in ("replace", "insert"):
                continue
            zeilen = [z for z in e[j1:j2] if z.strip() and z not in schon]
            if not zeilen:
                continue
            ueber = next((z for z in reversed(e[:j1]) if z.startswith("## ")), "")   # damit die Zeile ihren Abschnitt behält
            if ueber and ueber != kopf and not zeilen[0].startswith("#"):
                neu += ["", ueber]
                kopf = ueber
            neu += zeilen
    if neu:
        alt = LOKAL.read_text(encoding="utf-8-sig").rstrip() + "\n\n" if LOKAL.exists() else ""
        LOKAL.write_text(alt + "\n".join(neu).strip() + "\n", encoding="utf-8")
        print(f"Eigene Regeln aus Zweig {zweig} nach REGELN.lokal.md übernommen ({sum(1 for z in neu if z.strip())} Zeilen). Dem Besitzer zeigen.")
    if weg:
        print(f"In der Vorlage waren {len(weg)} Zeilen geändert oder entfernt. Sie gelten wieder, außer REGELN.lokal.md sagt etwas anderes:")
        for z in weg[:10]:
            print("   " + z[:120])
    _git("config", "zentrale.regelnUebernommen", zweig)


def block():
    t = (ORDNER / "REGELN.md").read_text(encoding="utf-8-sig").strip()
    t = re.sub(r"^# .*\n+", "", t)                    # Titel weg, dafür eigene Überschrift
    t = re.sub(r"^## ", "### ", t, flags=re.M)        # eine Stufe tiefer
    lokal = LOKAL.read_text(encoding="utf-8-sig").strip() if LOKAL.exists() else ""
    if lokal:
        lokal = re.sub(r"^#{1,3} ", "#### ", lokal, flags=re.M)
        t += f"\n\n### Eigene Regeln des Besitzers (aus `REGELN.lokal.md`, sie gehen den Regeln oben vor)\n\n{lokal}"
    client = ORDNER / "zentrale_client.py"
    kopf = (f"## Regeln des Besitzers (aus `REGELN.md` und `REGELN.lokal.md` in `{ORDNER}`, hier nicht ändern)\n\n"
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
    for i, x in enumerate(sys.argv):
        if x == "--ziel":
            if i + 1 >= len(sys.argv):
                sys.exit("--ziel braucht eine Datei.")
            ziel_merken(sys.argv[i + 1])
    if not pruefen and not weg:
        eigene_uebernehmen()
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
