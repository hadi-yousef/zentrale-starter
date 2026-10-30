"""Baut index.html aus index.src.html: setzt die benutzten Lucide-Symbole ein.

Aufruf: py zentrale/bauen.py [ordner mit lucide-static/icons] (Mac/Linux: python3),
Standard ist zentrale/vendor/lucide-icons.
Jeder Name in Anführungszeichen, zu dem es ein Lucide-Symbol gibt, landet in ICONS.
{{name}} im HTML wird direkt durch das fertige SVG ersetzt.
"""
import json
import re
import sys
from pathlib import Path

HIER = Path(__file__).resolve().parent
ICONS = Path(sys.argv[1]) if len(sys.argv) > 1 else HIER / "vendor" / "lucide-icons"
src = (HIER / "index.src.html").read_text(encoding="utf-8")


def inhalt(name):
    t = (ICONS / f"{name}.svg").read_text(encoding="utf-8")
    return re.sub(r"\s+", " ", re.search(r"<svg[^>]*>(.*)</svg>", t, re.S).group(1)).strip()


namen = sorted({n for n in re.findall(r"""["'`]([a-z][a-z0-9-]*)["'`]""", src) if (ICONS / f"{n}.svg").exists()})
namen = sorted(set(namen) | set(re.findall(r"\{\{([a-z0-9-]+)\}\}", src)))
out = src.replace("/*ICONS*/{}", json.dumps({n: inhalt(n) for n in namen}, ensure_ascii=False), 1)
out = re.sub(r"\{\{([a-z0-9-]+)\}\}", lambda m: f'<svg class="i" viewBox="0 0 24 24" aria-hidden="true">{inhalt(m.group(1))}</svg>', out)
(HIER / "index.html").write_text(out, encoding="utf-8")
print(f"index.html: {len(out) // 1024} kB, {len(namen)} Symbole")
