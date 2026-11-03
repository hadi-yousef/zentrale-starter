#!/usr/bin/env python3
r"""Bestandsaufnahme, nur lesend. Ändert, verschiebt und löscht nichts.

  py aufraeumen\inventur.py platz                                    freier Platz je Laufwerk
  py aufraeumen\inventur.py groessen $HOME\Documents $HOME\Pictures  Größe je Unterordner, größte zuerst
  py aufraeumen\inventur.py scannen $HOME [--json aufraeumen\inventur.json] [--gross 500]
  (Mac und Linux: python3 statt py, ~/Documents statt $HOME\Documents)

„scannen“ findet:
  - Projekte: Ordner mit .git oder typischen Projektdateien (package.json, pyproject.toml, *.xcodeproj, …)
  - Reste, die sich neu erzeugen lassen (node_modules, .venv, build, DerivedData, __pycache__, …) mit Größe
  - große Dateien (Standard ab 500 MB)
  - doppelte Dateien ab 1 MB (gleiche Größe, dann gleiche SHA-256)
Die Ausgabe ist Markdown und kann direkt in INVENTUR.md. Mit --json kommen alle Einzelheiten in eine Datei.
Dateien, die nur in der Cloud liegen (OneDrive „Dateien bei Bedarf“, iCloud), werden nie gelesen, sonst lädt Windows sie
herunter und füllt die Platte. Sie werden nur gezählt.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

from protokoll import nur_online

try:
    sys.stdout.reconfigure(errors="replace")
except (AttributeError, ValueError):
    pass

RESTE = {"node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".gradle", "DerivedData", "Pods",
         ".next", ".nuxt", ".parcel-cache", ".turbo", "target", "build", "dist", ".build", "out", ".tox", "bin", "obj"}
# Diese Reste zählen nur, wenn daneben Projektdateien liegen (sonst könnte „build“ oder „bin“ etwas Eigenes sein)
RESTE_NUR_IM_PROJEKT = {"target", "build", "dist", ".build", "out", "bin", "obj"}
PROJEKT_DATEIEN = {"package.json", "pyproject.toml", "setup.py", "requirements.txt", "Cargo.toml", "go.mod", "pom.xml",
                   "build.gradle", "build.gradle.kts", "CMakeLists.txt", "Makefile", "platformio.ini", "Package.swift",
                   "composer.json", "Gemfile", "pubspec.yaml", "deno.json"}
PROJEKT_ENDUNGEN = (".xcodeproj", ".xcworkspace", ".sln", ".csproj", ".ino", ".kicad_pro")
SYSTEM = {"AppData", "Windows", "Program Files", "Program Files (x86)", "ProgramData", "$Recycle.Bin", "$WinREAgent",
          "System Volume Information", "Recovery", "PerfLogs", "MSOCache", "Library", "Applications", "proc", "sys", "dev",
          "snap", ".Trash", ".cache", ".local", ".npm", ".cargo", ".rustup", ".gradle", ".m2", ".docker", "Papierkorb"}


def verbindung(p):
    """Link oder Windows-Verbindung (Junction, z. B. „Eigene Dateien“ im Profil): nicht hineingehen, sonst doppelt gezählt.
    os.walk folgt Junctions in jeder Python-Fassung. Geprüft wird die genaue Art (0xA0000003 = Junction), nicht nur „Reparse-Punkt“:
    Auch OneDrive-Ordner sind Reparse-Punkte, und die müssen gezählt und gesichert werden. Geht auch vor Python 3.12."""
    try:
        return os.path.islink(p) or getattr(os.lstat(p), "st_reparse_tag", 0) == 0xA0000003
    except OSError:
        return False


def groesse(b):
    for einheit, f in (("GB", 1e9), ("MB", 1e6), ("kB", 1e3)):
        if b >= f:
            return f"{b / f:.1f} {einheit}".replace(".", ",")
    return f"{b} Byte"


def ordnergroesse(p):
    n = 0
    for d, dirs, files in os.walk(p, onerror=lambda e: None):
        dirs[:] = [x for x in dirs if not verbindung(os.path.join(d, x))]
        for f in files:
            try:
                n += os.lstat(os.path.join(d, f)).st_size
            except OSError:
                pass
    return n


def platz():
    print("| Platte | Gesamt | Belegt | Frei |\n|---|---|---|---|")
    wurzeln = [f"{c}:\\" for c in "CDEFGHIJKLMNOPQRSTUVWXYZ" if os.path.exists(f"{c}:\\")] if os.name == "nt" else ["/", str(Path.home())]
    if os.name != "nt":
        for basis in ("/Volumes", "/media", "/mnt", "/run/media"):
            if os.path.isdir(basis):
                for d in sorted(os.listdir(basis)):
                    p = os.path.join(basis, d)
                    wurzeln += [p] + ([os.path.join(p, x) for x in os.listdir(p)] if basis == "/run/media" and os.access(p, os.R_OK) else [])
    gesehen = set()
    for w in wurzeln:
        try:
            u = shutil.disk_usage(w)
        except OSError:
            continue
        if (u.total, u.used) in gesehen:
            continue
        gesehen.add((u.total, u.used))
        print(f"| `{w}` | {groesse(u.total)} | {groesse(u.used)} | {groesse(u.free)} |")


def groessen(ordner):
    for o in ordner:
        o = Path(o).expanduser()
        zeilen = []
        for x in sorted(o.iterdir()) if o.is_dir() else []:
            if verbindung(x):
                continue
            b = ordnergroesse(x) if x.is_dir() else x.stat().st_size
            zeilen.append((b, x.name + ("/" if x.is_dir() else "")))
        print(f"\n### {o}  ({groesse(sum(b for b, _ in zeilen))})\n\n| Größe | Was |\n|---|---|")
        for b, name in sorted(zeilen, reverse=True)[:40]:
            print(f"| {groesse(b)} | `{name}` |")


def kopf_hash(p, n=1024 * 1024):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        h.update(f.read(n))
    return h.hexdigest()


def voll_hash(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for s in iter(lambda: f.read(1024 * 1024), b""):
            h.update(s)
    return h.hexdigest()


def scannen(ordner, gross_mb, json_datei):
    projekte, reste, grosse, nach_groesse, online = [], [], [], {}, 0
    for o in ordner:
        for d, dirs, files in os.walk(Path(o).expanduser(), onerror=lambda e: None):
            dp = Path(d)
            ist_projekt = ".git" in dirs or bool(PROJEKT_DATEIEN & set(files)) or any(x.endswith(PROJEKT_ENDUNGEN) for x in dirs + files)
            if ist_projekt and not any(str(dp).startswith(p["pfad"] + os.sep) for p in projekte):
                projekte.append({"pfad": str(dp), "git": ".git" in dirs})
            weiter = []
            for x in dirs:
                if x in RESTE and (x not in RESTE_NUR_IM_PROJEKT or ist_projekt):
                    reste.append({"pfad": str(dp / x), "bytes": ordnergroesse(dp / x)})
                elif not (x in SYSTEM or x == ".git" or verbindung(dp / x)):
                    weiter.append(x)
            dirs[:] = weiter
            for f in files:
                p = dp / f
                try:
                    st = p.lstat()
                except OSError:
                    continue
                if not p.is_file() or p.is_symlink():
                    continue
                if nur_online(st):
                    online += 1
                    continue
                if st.st_size >= gross_mb * 1e6:
                    grosse.append({"pfad": str(p), "bytes": st.st_size})
                if st.st_size >= 1e6:
                    nach_groesse.setdefault(st.st_size, []).append(str(p))
    doppelt = []
    for b, L in nach_groesse.items():
        if len(L) < 2:
            continue
        gruppen = {}
        for p in L:
            try:
                gruppen.setdefault(kopf_hash(p), []).append(p)
            except OSError:
                pass
        for G in gruppen.values():
            if len(G) < 2:
                continue
            voll = {}
            for p in G:
                try:
                    voll.setdefault(voll_hash(p), []).append(p)
                except OSError:
                    pass
            doppelt += [{"sha256": h, "bytes": b, "pfade": sorted(V)} for h, V in voll.items() if len(V) > 1]
    reste.sort(key=lambda r: -r["bytes"])
    grosse.sort(key=lambda r: -r["bytes"])
    doppelt.sort(key=lambda d: -d["bytes"] * (len(d["pfade"]) - 1))

    print(f"## Projekte ({len(projekte)})\n\n| Ordner | Git |\n|---|---|")
    for p in projekte:
        print(f"| `{p['pfad']}` | {'ja' if p['git'] else 'nein'} |")
    print(f"\n## Reste, die sich neu erzeugen ({groesse(sum(r['bytes'] for r in reste))})\n\n| Größe | Ordner |\n|---|---|")
    for r in reste[:60]:
        print(f"| {groesse(r['bytes'])} | `{r['pfad']}` |")
    print(f"\n## Große Dateien ab {gross_mb} MB ({len(grosse)})\n\n| Größe | Datei |\n|---|---|")
    for g in grosse[:60]:
        print(f"| {groesse(g['bytes'])} | `{g['pfad']}` |")
    spar = sum(d["bytes"] * (len(d["pfade"]) - 1) for d in doppelt)
    print(f"\n## Doppelte Dateien ({len(doppelt)} Gruppen, {groesse(spar)} doppelt belegt)\n")
    for d in doppelt[:40]:
        print(f"- {groesse(d['bytes'])} × {len(d['pfade'])}: " + ", ".join(f"`{p}`" for p in d["pfade"]))
    if online:
        print(f"\n{online} Dateien liegen nur in der Cloud und wurden nicht gelesen.")
    if json_datei:
        Path(json_datei).write_bytes(json.dumps({"projekte": projekte, "reste": reste, "gross": grosse, "doppelt": doppelt,
                                                 "nur_online": online}, ensure_ascii=False, indent=1).encode("utf-8"))
        print(f"\nEinzelheiten: {json_datei}")


def main():
    ap = argparse.ArgumentParser(description="Bestandsaufnahme, nur lesend.")
    sub = ap.add_subparsers(dest="befehl", required=True)
    sub.add_parser("platz", help="freier Platz je Platte")
    g = sub.add_parser("groessen", help="Größe je Unterordner"); g.add_argument("ordner", nargs="+")
    s = sub.add_parser("scannen", help="Projekte, Reste, Großes, Doppeltes"); s.add_argument("ordner", nargs="+")
    s.add_argument("--gross", type=int, default=500, help="große Dateien ab so vielen MB (Standard 500)")
    s.add_argument("--json", help="Einzelheiten zusätzlich in diese Datei")
    a = ap.parse_args()
    if a.befehl == "platz":
        platz()
    elif a.befehl == "groessen":
        groessen(a.ordner)
    else:
        scannen(a.ordner, a.gross, a.json)


if __name__ == "__main__":
    # Windows: bei Weiterleitung (Agenten lesen die Ausgabe) nimmt Python sonst cp1252, und „→“ oder Umlaute brechen ab
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    main()
