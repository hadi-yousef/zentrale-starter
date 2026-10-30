#!/usr/bin/env python3
r"""Unersetzliches auf einen Stick oder in einen Cloud-Ordner KOPIEREN, mit Prüfung. Die Quelle bleibt unverändert.

  py aufraeumen\sichern.py $HOME\Documents $HOME\Pictures --ziel E:\Sicherung --probe   zeigt Größe und Platz
  py aufraeumen\sichern.py $HOME\Documents $HOME\Pictures --ziel E:\Sicherung           kopiert
  (Mac und Linux: python3 statt py, Ziel z. B. /Volumes/STICK/Sicherung)

  - Prüft vorher, ob der Platz am Ziel reicht. Reicht er nicht, kopiert es nichts.
  - Kopiert nur, was am Ziel fehlt oder anders ist. Ein zweiter Lauf frischt also nur auf.
  - Lässt Reste weg, die sich neu erzeugen (node_modules, .venv, build, …), und versteckte Systemdateien (.DS_Store).
  - Prüft jede kopierte Datei mit SHA-256. Am Ende steht, was nicht geklappt hat.
  - Jede Quelle landet als eigener Ordner unter dem Ziel: --ziel E:\Sicherung + Pictures = E:\Sicherung\Pictures.
  - Dateien, die nur in der Cloud liegen (OneDrive „Dateien bei Bedarf“), werden nicht kopiert, sondern gezählt:
    Sie sind schon in der Cloud, und Lesen würde sie erst herunterladen.
  - Sticks mit FAT32 nehmen keine Dateien über 4 GB. Dann bricht es vor dem Kopieren ab; der Stick braucht exFAT oder NTFS.
"""
import argparse
import os
import shutil
import sys
from pathlib import Path

import protokoll as P
from inventur import RESTE, verbindung

WEG = {".DS_Store", "Thumbs.db", "desktop.ini"}


def dateien(quelle):
    if quelle.is_file():
        yield quelle, Path(quelle.name)
        return
    for d, dirs, files in os.walk(quelle, onerror=lambda e: print(f"  nicht lesbar: {e.filename}")):
        dirs[:] = [x for x in dirs if x not in RESTE and not verbindung(os.path.join(d, x))]
        for f in files:
            p = Path(d) / f
            if f not in WEG and not p.is_symlink():
                yield p, Path(quelle.name) / p.relative_to(quelle)


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

    plan, online = [], 0
    for q in a.quellen:
        q = Path(q).expanduser().absolute()
        if not q.exists():
            sys.exit(f"Gibt es nicht: {q}")
        for p, rel in dateien(q):
            z = ziel / rel
            try:
                st = p.stat()
                if P.nur_online(st):
                    online += 1
                    continue
                gr = st.st_size
                if z.exists() and z.stat().st_size == gr and P.sha256(z) == P.sha256(p):
                    continue
            except OSError as e:
                print(f"  nicht lesbar: {p} ({e})")
                continue
            plan.append((p, z, gr))
    if online:
        print(f"{online} Dateien liegen nur in der Cloud und werden nicht kopiert.")
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
        return
    fehler = []
    for i, (p, z, _) in enumerate(plan, 1):
        try:
            z.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, z)
            if P.sha256(p) != P.sha256(z):
                fehler.append(f"Prüfsumme anders: {p}")
        except OSError as e:
            fehler.append(f"{p}: {e}")
        if i % 200 == 0:
            print(f"  {i} von {len(plan)} …", flush=True)
    print(f"Fertig: {len(plan) - len(fehler)} Dateien kopiert und geprüft.")
    for f in fehler:
        print("Nicht geklappt: " + f)
    sys.exit(1 if fehler else 0)


if __name__ == "__main__":
    # Windows: bei Weiterleitung (Agenten lesen die Ausgabe) nimmt Python sonst cp1252, und „→“ oder Umlaute brechen ab
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    main()
