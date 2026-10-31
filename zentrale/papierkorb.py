"""Zentrale: Papierkorb (Seite „Papierkorb“). Was die Agenten weggeräumt haben, an einem Ort.

Zwei Quellen, beide auf derselben Platte wie vorher, gelöscht wurde nichts:
  - Aufräumen: Schritte mit art „papierkorb“ aus aufraeumen/protokoll.jsonl (verschoben mit verschieben.py --papierkorb),
    die noch nicht zurückgeholt und nicht endgültig gelöscht sind. Sie liegen in <Laufwerk>:\\Papierkorb\\<datum>\\….
  - Notizen: Dateien im versteckten Ordner .papierkorb/<datum>/… im Notizen-Ordner.

Zurücklegen dürfen Agenten und der Besitzer. **Endgültig löschen darf nur der Besitzer** (Schlüssel „besitzer“),
das prüft app.py, und auch hier nur, was wirklich in einem Ordner „Papierkorb“ bzw. „.papierkorb“ liegt.
"""
import os
import shutil
import sys
import threading
from pathlib import Path

import hub
import notizen

AUFRAEUMEN = Path(__file__).resolve().parent.parent / "aufraeumen"
sys.path.insert(0, str(AUFRAEUMEN))
import protokoll as P       # noqa: E402
import rueckgaengig as R    # noqa: E402

_sperre = threading.Lock()


def _schritte():
    alle = P.lesen()
    weg = {e["zurueck_von"] for e in alle if e.get("art") == "zurueck"} | {e["geloescht_von"] for e in alle if e.get("art") == "geloescht"}
    return [e for e in alle if e.get("art") == "papierkorb" and e["nr"] not in weg]


def _im_papierkorb(p, name="Papierkorb"):
    """Liegt p unterhalb eines Ordners mit diesem Namen (und ist nicht der Ordner selbst)?"""
    p = Path(p).absolute()
    return any(x.name.lower() == name.lower() for x in p.parents)


def liste():
    E = []
    for e in reversed(_schritte()):
        da = Path(e["nach"]).exists() or Path(e["nach"]).is_symlink()
        E.append({"art": "aufraeumen", "nr": e["nr"], "name": Path(e["von"]).name, "von": e["von"], "nach": e["nach"],
                  "typ": e.get("typ", ""), "bytes": e.get("bytes") or 0, "dateien": e.get("dateien") or 0,
                  "grund": e.get("grund", ""), "zeit": e.get("zeit", ""), "da": da})
    N = []
    korb = notizen.PAPIERKORB
    if korb.is_dir():
        for d, dirs, files in os.walk(korb):
            for f in files:
                p = Path(d) / f
                rel = p.relative_to(korb).as_posix()          # <datum>/<alter pfad>
                tag, _, alt = rel.partition("/")
                try:
                    st = p.stat()
                except OSError:
                    continue
                N.append({"art": "notiz", "pfad": rel, "name": Path(alt or rel).stem, "von": alt, "tag": tag, "bytes": st.st_size,
                          "zeit_s": int(st.st_mtime)})
    N.sort(key=lambda x: -x["zeit_s"])
    return {"eintraege": E, "notizen": N, "bytes": sum(x["bytes"] for x in E if x["da"]) + sum(x["bytes"] for x in N)}


def _schritt(nr):
    try:
        nr = int(nr)
    except (TypeError, ValueError):
        raise ValueError("nr fehlt")
    e = next((x for x in _schritte() if x["nr"] == nr), None)
    if not e:
        raise ValueError("Diesen Eintrag gibt es nicht (mehr) im Papierkorb.")
    return e


def _notiz(pfad):
    pfad = str(pfad or "").replace("\\", "/").strip("/")
    p = (notizen.PAPIERKORB / pfad).resolve()
    if notizen.PAPIERKORB.resolve() not in p.parents or not p.is_file():
        raise ValueError("Diese Notiz liegt nicht (mehr) im Papierkorb.")
    tag, _, alt = pfad.partition("/")
    return p, alt


class _protokoll_sperre:
    """P.sperre(), aber „belegt“ wird zu einer normalen Meldung statt zum Programmende."""
    def __enter__(self):
        self._s = P.sperre()
        try:
            return self._s.__enter__()
        except SystemExit as e:
            raise ValueError(str(e))

    def __exit__(self, *a):
        return self._s.__exit__(*a)


def _schreibschutz_weg(fn, pfad, _):
    """Windows: schreibgeschützte Dateien (z. B. aus .git) lassen sich erst nach chmod löschen."""
    os.chmod(pfad, 0o700)
    fn(pfad)


def zuruecklegen(b):
    """An den alten Platz zurück. Gibt es dort schon etwas, bleibt es im Papierkorb und es kommt eine Meldung."""
    with _sperre:
        if b.get("notiz"):
            p, alt = _notiz(b["notiz"])
            rel, ziel = notizen._sicher(alt)
            if ziel.exists():
                raise ValueError(f"Am alten Platz liegt schon eine Notiz „{rel}“. Bitte erst umbenennen.")
            ziel.parent.mkdir(parents=True, exist_ok=True)
            os.replace(p, ziel)
            return {"ok": True, "pfad": rel}
        try:
            fehler = R.zurueck(_schritt(b.get("nr")), probe=False, trotzdem=False)
        except SystemExit as e:   # Sperre belegt: ein Agent räumt gerade auf
            raise ValueError(str(e))
        if fehler:
            raise ValueError(fehler)
        return {"ok": True}


def loeschen(b):
    """Endgültig löschen (nur der Besitzer, siehe app.py). Kommt ins Protokoll."""
    with _sperre:
        if b.get("notiz"):
            p, _ = _notiz(b["notiz"])
            p.unlink()
            return {"ok": True}
        e = _schritt(b.get("nr"))
        p = Path(e["nach"])
        if not _im_papierkorb(p):
            raise ValueError("Das liegt nicht in einem Papierkorb-Ordner. Es wird nichts gelöscht.")
        with _protokoll_sperre():
            if p.is_dir() and not p.is_symlink():
                shutil.rmtree(p, onerror=_schreibschutz_weg)
            elif p.exists() or p.is_symlink():
                p.unlink()
            P.eintragen({"art": "geloescht", "geloescht_von": e["nr"], "von": e["nach"], "nach": "", "bytes": e.get("bytes"),
                         "dateien": e.get("dateien"), "grund": "vom Besitzer in der Zentrale endgültig gelöscht"})
        return {"ok": True}
