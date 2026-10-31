#!/usr/bin/env python3
"""Trägt den Hook `claude_lauf.py` in die Einstellungen von Claude Code ein (für alle Projekte dieses Benutzers).

Aufruf: py hooks/einrichten.py            (Mac/Linux: python3)
        py hooks/einrichten.py --weg      (wieder austragen)

Die Datei ist %USERPROFILE%\\.claude\\settings.json (Mac/Linux: ~/.claude/settings.json). Vorher wird eine Kopie daneben
gelegt (settings.json.vor-zentrale-<zeit>). Andere Einstellungen und Hooks bleiben, wie sie sind. Zweimal aufrufen
schadet nicht. Danach Claude Code (T3) einmal neu starten.
"""
import json
import shutil
import sys
import time
from pathlib import Path

HOOK = Path(__file__).resolve().parent / "claude_lauf.py"
DATEI = Path.home() / ".claude" / "settings.json"
EREIGNISSE = ("UserPromptSubmit", "Stop")


def befehl():
    # Schrägstriche nach vorn und in Anführungszeichen: so geht der Befehl in cmd, PowerShell und Git Bash
    py = Path(sys.executable).as_posix()
    return f'"{py}" "{HOOK.as_posix()}"'


def ist_unserer(h):
    return isinstance(h, dict) and "claude_lauf.py" in str(h.get("command", ""))


def main():
    weg = "--weg" in sys.argv
    try:
        d = json.loads(DATEI.read_text(encoding="utf-8-sig")) if DATEI.exists() else {}
    except ValueError as e:
        sys.exit(f"{DATEI} ist kein gültiges JSON ({e}). Nichts geändert.")
    if not isinstance(d, dict):
        sys.exit(f"{DATEI} hat eine unerwartete Form. Nichts geändert.")
    if DATEI.exists():
        kopie = DATEI.with_name(f"settings.json.vor-zentrale-{time.strftime('%Y%m%d-%H%M%S')}")
        if not kopie.exists():   # zweimal in derselben Sekunde: die erste Kopie (der Stand davor) bleibt
            shutil.copy2(DATEI, kopie)
            print(f"Kopie: {kopie}")
    hooks = d.setdefault("hooks", {})
    for e in EREIGNISSE:
        gruppen = [g for g in hooks.get(e) or [] if isinstance(g, dict)]
        for g in gruppen:   # alte Einträge von uns entfernen (auch mit anderem Pfad)
            g["hooks"] = [h for h in g.get("hooks") or [] if not ist_unserer(h)]
        gruppen = [g for g in gruppen if g.get("hooks")]
        if not weg:
            gruppen.append({"hooks": [{"type": "command", "command": befehl(), "timeout": 5}]})
        if gruppen:
            hooks[e] = gruppen
        else:
            hooks.pop(e, None)
    if not hooks:
        d.pop("hooks", None)
    DATEI.parent.mkdir(parents=True, exist_ok=True)
    DATEI.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(("Ausgetragen" if weg else f"Eingetragen: {befehl()}") + f"\nin {DATEI}. Claude Code (T3) einmal neu starten.")


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    main()
