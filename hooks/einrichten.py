#!/usr/bin/env python3
"""Trägt den Hook `claude_lauf.py` in die Einstellungen von Claude Code ein (für alle Projekte dieses Benutzers).

Aufruf: py hooks/einrichten.py            (Mac/Linux: python3)
        py hooks/einrichten.py --weg      (wieder austragen)

Die Datei ist %USERPROFILE%\\.claude\\settings.json (Mac/Linux: ~/.claude/settings.json). Vorher wird eine Kopie daneben
gelegt (settings.json.vor-zentrale-<zeit>). Andere Einstellungen und Hooks bleiben, wie sie sind. Zweimal aufrufen
schadet nicht: Ist alles schon da, wird nichts geschrieben und keine Kopie gelegt. Ein vorhandener Eintrag bleibt an seiner Stelle,
auch mit anderem Python-Pfad; ersetzt wird er nur, wenn sein Skript nicht mehr da ist. Danach Claude Code (T3) einmal neu starten.
"""
import json
import re
import shutil
import sys
import time
from pathlib import Path

HOOK = Path(__file__).resolve().parent / "claude_lauf.py"
DATEI = Path.home() / ".claude" / "settings.json"
EREIGNISSE = ("UserPromptSubmit", "Stop", "StopFailure")   # StopFailure: Antwort brach an einem API-Fehler ab (z. B. Limit), dann kommt kein Stop


def befehl():
    # Schrägstriche nach vorn und in Anführungszeichen: so geht der Befehl in cmd, PowerShell und Git Bash
    py = Path(sys.executable).as_posix()
    return f'"{py}" "{HOOK.as_posix()}"'


def ist_unserer(h):
    return isinstance(h, dict) and "claude_lauf.py" in str(h.get("command", ""))


def _skript(h):
    """Pfad zu claude_lauf.py aus einem eingetragenen Befehl (in Anführungszeichen oder ohne)."""
    m = re.search(r'"([^"]*claude_lauf\.py)"|(\S*claude_lauf\.py)', str(h.get("command", "")))
    return Path(m.group(1) or m.group(2)) if m else None


def main():
    weg = "--weg" in sys.argv
    try:
        d = json.loads(DATEI.read_text(encoding="utf-8-sig")) if DATEI.exists() else {}
    except ValueError as e:
        sys.exit(f"{DATEI} ist kein gültiges JSON ({e}). Nichts geändert.")
    if not isinstance(d, dict):
        sys.exit(f"{DATEI} hat eine unerwartete Form. Nichts geändert.")
    vorher = json.dumps(d, sort_keys=True)
    hooks = d.setdefault("hooks", {})
    for e in EREIGNISSE:
        gruppen = [g for g in hooks.get(e) or [] if isinstance(g, dict)]
        unsere = [h for g in gruppen for h in g.get("hooks") or [] if ist_unserer(h)]
        gut = [h for h in unsere if (_skript(h) or Path("/fehlt")).exists()]
        if not weg and gut:   # schon da und das Skript gibt es: so lassen, auch die Reihenfolge
            for g in gruppen:   # nur Doppelte und kaputte Einträge von uns weg
                g["hooks"] = [h for h in g.get("hooks") or [] if not ist_unserer(h) or h is gut[0]]
        else:
            for g in gruppen:   # alte Einträge von uns entfernen (auch mit anderem Pfad)
                g["hooks"] = [h for h in g.get("hooks") or [] if not ist_unserer(h)]
        gruppen = [g for g in gruppen if g.get("hooks")]
        if not weg and not gut:
            gruppen.append({"hooks": [{"type": "command", "command": befehl(), "timeout": 5}]})
        if gruppen:
            hooks[e] = gruppen
        else:
            hooks.pop(e, None)
    if not hooks:
        d.pop("hooks", None)
    if json.dumps(d, sort_keys=True) == vorher:
        print(("Nichts einzutragen, der Hook war nicht da." if weg else "Der Hook ist schon eingetragen, nichts geändert.") + f" ({DATEI})")
        return
    if DATEI.exists():
        kopie = DATEI.with_name(f"settings.json.vor-zentrale-{time.strftime('%Y%m%d-%H%M%S')}")
        if not kopie.exists():   # zweimal in derselben Sekunde: die erste Kopie (der Stand davor) bleibt
            shutil.copy2(DATEI, kopie)
            print(f"Kopie: {kopie}")
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
