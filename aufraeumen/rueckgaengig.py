#!/usr/bin/env python3
r"""Schritte aus aufraeumen/protokoll.jsonl zurückschieben.

  py aufraeumen\rueckgaengig.py --liste           alle Schritte, die noch zurück können
  py aufraeumen\rueckgaengig.py 12                Schritt 12 zurück
  py aufraeumen\rueckgaengig.py 12 13 14          mehrere (geht immer vom neuesten zum ältesten)
  py aufraeumen\rueckgaengig.py --ab 10           Schritt 10 und alle danach
  py aufraeumen\rueckgaengig.py --alles           alles
  … --probe                                       nur zeigen, nichts tun
  (Mac und Linux: python3 statt py. Die Pfade im Protokoll sind die des Rechners, auf dem verschoben wurde.)

Vor dem Zurückschieben wird geprüft, ob am Ziel noch dasselbe liegt (Prüfsumme bei Dateien, Anzahl und Größe bei Ordnern)
und ob der alte Platz frei ist. Passt etwas nicht, bleibt der Schritt stehen und wird gemeldet (mit --trotzdem geht es
auch bei geänderter Größe). Jedes Zurück kommt selbst ins Protokoll.
"""
import argparse
import os
import sys
from pathlib import Path

import protokoll as P


def offen(alle):
    zurueck = {e["zurueck_von"] for e in alle if e.get("art") == "zurueck"}
    return [e for e in alle if e.get("art") in ("verschieben", "papierkorb") and e["nr"] not in zurueck]


def zurueck(e, probe, trotzdem):
    von, nach = Path(e["nach"]), Path(e["von"])
    if not (von.exists() or von.is_symlink()):
        return f"Schritt {e['nr']}: liegt nicht mehr hier: {von}"
    if nach.exists() or nach.is_symlink():
        return f"Schritt {e['nr']}: der alte Platz ist belegt: {nach}"
    m = P.messen(von)
    if e.get("sha256") and m.get("sha256") != e["sha256"]:
        return f"Schritt {e['nr']}: die Datei hat sich geändert (Prüfsumme anders). Bitte von Hand ansehen: {von}"
    if (m["bytes"], m["dateien"]) != (e.get("bytes"), e.get("dateien")) and not trotzdem:
        return (f"Schritt {e['nr']}: Größe oder Anzahl anders ({m['bytes']} Byte in {m['dateien']} Dateien statt "
                f"{e.get('bytes')} Byte in {e.get('dateien')}). Mit --trotzdem geht es trotzdem.")
    print(f"{'Probe: ' if probe else ''}Schritt {e['nr']}: {von}\n  → {nach}")
    if probe:
        return None
    with P.sperre():
        try:
            nach.parent.mkdir(parents=True, exist_ok=True)
            os.rename(von, nach)
        except OSError as fehler:
            return f"Schritt {e['nr']}: {fehler}"
        n = P.eintragen({"art": "zurueck", "zurueck_von": e["nr"], "von": str(von), "nach": str(nach), **m, "grund": "rückgängig"})
    print(f"  zurück (Schritt Nr. {n['nr']} im Protokoll)")
    return None


def main():
    ap = argparse.ArgumentParser(description="Schritte aus dem Aufräum-Protokoll zurückschieben.")
    ap.add_argument("nr", nargs="*", type=int)
    ap.add_argument("--liste", action="store_true")
    ap.add_argument("--ab", type=int)
    ap.add_argument("--alles", action="store_true")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--trotzdem", action="store_true", help="auch wenn Größe oder Anzahl bei Ordnern anders ist")
    a = ap.parse_args()

    O = offen(P.lesen())
    if a.liste or not (a.nr or a.ab or a.alles):
        if not O:
            return print("Nichts zurückzuschieben.")
        for e in O:
            print(f"{e['nr']:>4}  {e['zeit']}  {e['art']:<11} {e['von']}\n      → {e['nach']}  ({P.groesse(e.get('bytes') or 0)}){'  · ' + e['grund'] if e.get('grund') else ''}")
        return
    if a.alles:
        wahl = O
    elif a.ab:
        wahl = [e for e in O if e["nr"] >= a.ab]
    else:
        wahl = [e for e in O if e["nr"] in a.nr]
        fehlt = set(a.nr) - {e["nr"] for e in wahl}
        if fehlt:
            print(f"Nicht (mehr) offen: {', '.join(map(str, sorted(fehlt)))}")
    probleme = [p for p in (zurueck(e, a.probe, a.trotzdem) for e in sorted(wahl, key=lambda e: -e["nr"])) if p]
    for p in probleme:
        print("Nicht zurück: " + p)
    sys.exit(1 if probleme else 0)


if __name__ == "__main__":
    # Windows: bei Weiterleitung (Agenten lesen die Ausgabe) nimmt Python sonst cp1252, und „→“ oder Umlaute brechen ab
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    main()
