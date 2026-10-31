#!/usr/bin/env python3
r"""Unersetzliches auf einen Stick oder in einen Cloud-Ordner KOPIEREN, mit Prüfung. Die Quelle bleibt unverändert.

  py aufraeumen\sichern.py $HOME\Documents $HOME\Pictures --ziel E:\Sicherung --probe   zeigt Größe und Platz
  py aufraeumen\sichern.py $HOME\Documents $HOME\Pictures --ziel E:\Sicherung           kopiert
  (Mac und Linux: python3 statt py, Ziel z. B. /Volumes/STICK/Sicherung)

  - Prüft vorher, ob der Platz am Ziel reicht. Reicht er nicht, kopiert es nichts.
  - Kopiert nur, was am Ziel fehlt oder anders ist. Ein zweiter Lauf frischt also nur auf.
  - Lässt Reste weg, die sich neu erzeugen (node_modules, .venv, __pycache__, …), und versteckte Systemdateien (.DS_Store).
    Mehrdeutige Namen wie build, bin, dist, out, target bleiben drin, außer sie liegen in einem Projekt (wie inventur.py).
    Jeder ausgelassene Ordner steht mit Grund in der Ausgabe und im Verzeichnis am Ziel.
  - Prüft jede kopierte Datei mit SHA-256. Am Ende steht, was nicht geklappt hat.
  - Jede Quelle landet als eigener Ordner unter dem Ziel: --ziel E:\Sicherung + Pictures = E:\Sicherung\Pictures.
    Heißen zwei Quellen gleich (A\Documents und B\Documents), bricht es vor dem ersten Kopieren ab.
  - Am Ende prüft es, dass jede ausgewählte Datei am Ziel liegt, und schreibt das Verzeichnis _sicherung.json ans Ziel
    (je Datei Pfad, Größe, SHA-256; dazu Ausgelassenes mit Grund). Konnte etwas nicht gelesen werden, endet es mit Fehler.
  - Dateien, die nur in der Cloud liegen (OneDrive „Dateien bei Bedarf“), werden nicht kopiert, sondern gezählt:
    Sie sind schon in der Cloud, und Lesen würde sie erst herunterladen.
  - Sticks mit FAT32 nehmen keine Dateien über 4 GB. Dann bricht es vor dem Kopieren ab; der Stick braucht exFAT oder NTFS.
"""
import argparse
import datetime
import json
import os
import shutil
import sys
from pathlib import Path

import protokoll as P
from inventur import PROJEKT_DATEIEN, PROJEKT_ENDUNGEN, RESTE, RESTE_NUR_IM_PROJEKT, verbindung

WEG = {".DS_Store", "Thumbs.db", "desktop.ini"}
VERZEICHNIS = "_sicherung.json"


def rest_grund(d, x, dirs, files):
    """Warum der Unterordner x von d ausgelassen wird, oder None (dann wird er gesichert). Im Zweifel sichern."""
    if x not in RESTE:
        return None
    if x in RESTE_NUR_IM_PROJEKT:
        projekt = ".git" in dirs or bool(PROJEKT_DATEIEN & set(files)) or any(n.endswith(PROJEKT_ENDUNGEN) for n in dirs + files)
        return "Bau-Rest im Projekt, erzeugt sich neu" if projekt else None
    if x in (".venv", "venv"):
        return "Python-Umgebung, erzeugt sich neu" if os.path.isfile(os.path.join(d, x, "pyvenv.cfg")) else None
    return "erzeugt sich neu"


def dateien(quelle, fehler, aus):
    """Alle Dateien der Quelle als (pfad, ziel-relativ). Nicht Lesbares kommt in fehler, Ausgelassenes mit Grund in aus."""
    if quelle.is_file():
        yield quelle, Path(quelle.name)
        return
    for d, dirs, files in os.walk(quelle, onerror=lambda e: fehler.append(f"nicht lesbar: {e.filename} ({e.strerror})")):
        weiter = []
        for x in dirs:
            grund = "Verknüpfung" if verbindung(os.path.join(d, x)) else rest_grund(d, x, dirs, files)
            if grund:
                aus.append({"pfad": os.path.join(d, x), "grund": grund})
            else:
                weiter.append(x)
        dirs[:] = weiter
        for f in files:
            p = Path(d) / f
            if f in WEG:
                continue
            if p.is_symlink():
                aus.append({"pfad": str(p), "grund": "Verknüpfung"})
                continue
            yield p, Path(quelle.name) / p.relative_to(quelle)


def schluessel(rel):
    """Vergleich wie am Ziel: Sticks (exFAT, FAT32), Windows und Mac unterscheiden Groß- und Kleinschreibung nicht."""
    return str(rel).replace("\\", "/").casefold()


def fat32(pfad):
    """Ist das Ziel mit FAT32 formatiert (höchstens 4 GB je Datei)? Nur unter Windows sicher feststellbar."""
    if os.name != "nt":
        return False
    import ctypes
    name = ctypes.create_unicode_buffer(64)
    ok = ctypes.windll.kernel32.GetVolumeInformationW(ctypes.c_wchar_p(Path(pfad).anchor), None, 0, None, None, None, name, 64)
    return bool(ok) and name.value.upper().startswith("FAT")


def main():
    ap = argparse.ArgumentParser(description="Kopieren mit SHA-256-Prüfung, nur was fehlt.")
    ap.add_argument("quellen", nargs="+")
    ap.add_argument("--ziel", required=True)
    ap.add_argument("--probe", action="store_true", help="nur Größe und Platz zeigen")
    a = ap.parse_args()
    ziel = Path(a.ziel).expanduser().absolute()

    quellen, namen = [], {}
    for q in a.quellen:
        q = Path(q).expanduser().absolute()
        if not q.exists():
            sys.exit(f"Gibt es nicht: {q}")
        k = schluessel(q.name)
        if k in namen:
            sys.exit(f"Zwei Quellen landen am selben Ort im Ziel ({ziel / q.name}): {namen[k]} und {q}. "
                     f"Bitte einzeln sichern, jede mit eigenem Ziel (z. B. --ziel {ziel / 'A'}). Kopiert wurde nichts.")
        namen[k] = q
        quellen.append(q)

    plan, alle, aus, fehler, online, wohin, summen = [], [], [], [], 0, {}, {}
    for q in quellen:
        for p, rel in dateien(q, fehler, aus):
            k = schluessel(rel)
            if k in wohin:   # z. B. „Bild.JPG“ und „bild.jpg“ unter Linux: am Ziel wäre es dieselbe Datei
                sys.exit(f"Zwei Dateien landen am selben Ort im Ziel ({ziel / rel}): {wohin[k]} und {p}. Kopiert wurde nichts.")
            wohin[k] = p
            z = ziel / rel
            try:
                st = p.stat()
                if P.nur_online(st):
                    online += 1
                    aus.append({"pfad": str(p), "grund": "liegt nur in der Cloud"})
                    continue
                gr = st.st_size
                alle.append((p, z, rel, gr))
                if z.exists() and z.stat().st_size == gr:
                    hz = P.sha256(z)
                    if hz == P.sha256(p):
                        summen[z] = hz
                        continue
            except OSError as e:
                fehler.append(f"nicht lesbar: {p} ({e})")
                continue
            plan.append((p, z, gr))
    if online:
        print(f"{online} Dateien liegen nur in der Cloud und werden nicht kopiert.")
    ordner_aus = [x for x in aus if x["grund"] not in ("liegt nur in der Cloud",)]
    if ordner_aus:
        print(f"Ausgelassen ({len(ordner_aus)}):")
        for x in ordner_aus[:30]:
            print(f"  {x['grund']}: {x['pfad']}")
        if len(ordner_aus) > 30:
            print(f"  … und {len(ordner_aus) - 30} weitere (alle im Verzeichnis {VERZEICHNIS} am Ziel)")
    for f in fehler:
        print("  " + f)
    noetig = sum(g for _, _, g in plan)
    pruef = ziel
    while not pruef.exists():
        pruef = pruef.parent
    frei = shutil.disk_usage(pruef).free
    print(f"Zu kopieren: {len(plan)} Dateien, {P.groesse(noetig)}. Frei am Ziel: {P.groesse(frei)}.")
    if noetig > frei * 0.95:
        sys.exit("Der Platz reicht nicht. Bitte weniger auswählen oder ein größeres Ziel nehmen. Kopiert wurde nichts.")
    zu_gross = [p for p, _, g in plan if g >= 4 * 1024 ** 3]
    if zu_gross and fat32(pruef):
        sys.exit(f"Das Ziel ist FAT32 und nimmt keine Dateien über 4 GB, z. B. {zu_gross[0]}. Kopiert wurde nichts.")
    if a.probe:
        if fehler:
            sys.exit(f"{len(fehler)} Stellen ließen sich nicht lesen (siehe oben). Die Sicherung wäre unvollständig.")
        return
    lesefehler, kopiert = len(fehler), 0
    for i, (p, z, _) in enumerate(plan, 1):
        try:
            z.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, z)
            h = P.sha256(p)
            if h != P.sha256(z):
                fehler.append(f"Prüfsumme anders: {p}")
            else:
                kopiert += 1
                summen[z] = h
        except OSError as e:
            fehler.append(f"{p}: {e}")
        if i % 200 == 0:
            print(f"  {i} von {len(plan)} …", flush=True)
    # Schluss: liegt jede ausgewählte Datei am Ziel, in der richtigen Größe? Ein Zwischenstand mit richtiger Prüfsumme genügt nicht.
    eintraege = []
    for p, z, rel, gr in alle:
        try:
            ok = z.stat().st_size == gr
            h = summen.get(z) or P.sha256(z)
        except OSError:
            ok, h = False, None
        if not ok:
            fehler.append(f"fehlt am Ziel oder falsche Größe: {z}")
        eintraege.append({"pfad": str(rel).replace("\\", "/"), "bytes": gr, "sha256": h})
    try:
        ziel.mkdir(parents=True, exist_ok=True)
        tmp = ziel / (VERZEICHNIS + ".tmp")
        tmp.write_text(json.dumps({"zeit": datetime.datetime.now().isoformat(timespec="seconds"),
                                   "quellen": [str(q) for q in quellen], "dateien": eintraege, "ausgelassen": aus,
                                   "fehler": fehler, "vollstaendig": not fehler}, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(ziel / VERZEICHNIS)
    except OSError as e:
        fehler.append(f"Verzeichnis {VERZEICHNIS} nicht geschrieben: {e}")
    print(f"Fertig: {kopiert} Dateien kopiert und geprüft, {len(alle)} Dateien liegen jetzt am Ziel.")
    for f in fehler[lesefehler:]:
        print("Nicht geklappt: " + f)
    if fehler:
        sys.exit(f"UNVOLLSTÄNDIG: {len(fehler)} Fehler (auch nicht Lesbares oben). Diese Sicherung nicht als vollständig ansehen.")


if __name__ == "__main__":
    # Windows: bei Weiterleitung (Agenten lesen die Ausgabe) nimmt Python sonst cp1252, und „→“ oder Umlaute brechen ab
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    main()
