#!/usr/bin/env python3
r"""Datei oder Ordner verschieben, nur auf derselben Platte, mit Eintrag im Protokoll. Löscht nie etwas.

  py aufraeumen\verschieben.py <von> <nach> --grund "In den Projektordner"
  py aufraeumen\verschieben.py --papierkorb <pfad> --grund "Doppelt, Original liegt in Bilder\2021"
  py aufraeumen\verschieben.py ... --probe        zeigt nur, was passieren würde
  (Mac und Linux: python3 statt py, / statt \)

Regeln:
  - Nur auf derselben Platte. Verschieben kostet dort keinen Platz und geht sofort. Über Plattengrenzen bricht es ab,
    denn das wäre Kopieren und Löschen.
  - Gibt es das Ziel schon, bricht es ab (beim Papierkorb bekommt der Name „ (2)“ dazu).
  - „<nach>“ ist der neue volle Pfad, nicht der Ordner, in den es soll.
  - Jeder Schritt kommt in aufraeumen/protokoll.jsonl. Zurück geht es mit rueckgaengig.py.
  - Der Papierkorb liegt auf derselben Platte (Windows: C:\Papierkorb bzw. D:\Papierkorb; Mac und Linux: ~/Papierkorb).
    Darunter ein Ordner je Tag und der alte Pfad. Leeren tut nur der Besitzer.
  - Unter Windows schlägt Verschieben fehl, solange ein Programm die Datei offen hat. Dann das Programm schließen.
"""
import argparse
import datetime
import os
import sys
from pathlib import Path

import protokoll as P


def pruefen(von, nach):
    if not (von.exists() or von.is_symlink()):
        sys.exit(f"Gibt es nicht: {von}")
    if von == Path.home() or von.parent == von or von == P.HIER.parent or P.HIER.parent in von.parents or von in P.HIER.parents:
        sys.exit(f"Das verschiebe ich nicht: {von}")
    if nach == von or von in nach.parents:
        sys.exit("Das Ziel liegt in der Quelle selbst.")
    if nach.exists() or nach.is_symlink():
        sys.exit(f"Ziel gibt es schon: {nach}")
    if P.platte(von) != P.platte(nach.parent):
        sys.exit("Ziel liegt auf einer anderen Platte. Das wäre Kopieren und Löschen; dafür ist dieses Skript nicht da.")


def main():
    ap = argparse.ArgumentParser(description="Verschieben auf derselben Platte, mit Protokoll. Löscht nie.")
    ap.add_argument("von")
    ap.add_argument("nach", nargs="?")
    ap.add_argument("--papierkorb", action="store_true", help="in den Papierkorb derselben Platte verschieben")
    ap.add_argument("--grund", default="", help="ein Satz, warum")
    ap.add_argument("--probe", action="store_true", help="nur zeigen, nichts tun")
    a = ap.parse_args()

    von = Path(a.von).expanduser().absolute()
    if a.papierkorb:
        if a.nach:
            ap.error("Mit --papierkorb kein Ziel angeben.")
        korb = P.papierkorb_fuer(von)
        basis = Path(von.anchor) if P.WINDOWS else Path.home() if korb == Path.home() / "Papierkorb" else korb.parent
        try:
            rel = von.relative_to(basis)
        except ValueError:
            rel = Path(von.name)
        if korb == von or korb in von.parents:
            sys.exit("Das liegt schon im Papierkorb.")
        nach = P.frei(korb / datetime.date.today().isoformat() / rel)
    elif a.nach:
        nach = Path(a.nach).expanduser().absolute()
    else:
        ap.error("Ziel fehlt (oder --papierkorb).")

    pruefen(von, nach)
    m = P.messen(von)
    print(f"{'Probe: ' if a.probe else ''}{von}\n  → {nach}\n  {m['typ']}, {P.groesse(m['bytes'])}, {m['dateien']} Dateien")
    if a.probe:
        return
    with P.sperre():
        try:
            nach.parent.mkdir(parents=True, exist_ok=True)
            os.rename(von, nach)   # gleiche Platte: nur ein neuer Name, nichts wird kopiert. Über Platten hinweg schlägt es fehl.
        except OSError as fehler:
            sys.exit(f"Nicht verschoben: {fehler}")
        e = P.eintragen({"art": "papierkorb" if a.papierkorb else "verschieben", "von": str(von), "nach": str(nach), **m, "grund": a.grund})
    print(f"  Schritt Nr. {e['nr']} im Protokoll. Zurück: {P.PY} {Path('aufraeumen') / 'rueckgaengig.py'} {e['nr']}")


if __name__ == "__main__":
    # Windows: bei Weiterleitung (Agenten lesen die Ausgabe) nimmt Python sonst cp1252, und „→“ oder Umlaute brechen ab
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    main()
