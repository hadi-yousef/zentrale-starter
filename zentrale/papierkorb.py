r"""Zentrale: Papierkorb (Seite „Papierkorb“). Was die Agenten weggeräumt haben, an einem Ort.

Zwei Quellen, beide auf derselben Platte wie vorher, gelöscht wurde nichts:
  - Aufräumen: Schritte mit art „papierkorb“ aus aufraeumen/protokoll.jsonl (verschoben mit verschieben.py --papierkorb),
    die noch nicht zurückgeholt und nicht endgültig gelöscht sind. Sie liegen in <Laufwerk>:\Papierkorb\<datum>\….
  - Notizen: Dateien im versteckten Ordner .papierkorb/<datum>/… im Notizen-Ordner.

Wie in der Zentrale des Vorbilds: je Papierkorb (C:\Papierkorb, D:\Papierkorb, Notizen) ein Abschnitt mit Größe und
„Alles leeren“, dazu der Windows-Papierkorb (was im Explorer gelöscht wurde) mit Größe und „Leeren“.
Zurücklegen dürfen Agenten und der Besitzer. **Endgültig löschen darf nur der Besitzer** (Schlüssel „besitzer“),
das prüft app.py, und auch hier nur, was wirklich in einem Ordner „Papierkorb“ bzw. „.papierkorb“ liegt.
"""
import os
import shutil
import string
import subprocess
import sys
import threading
import time
from pathlib import Path

import hub
import notizen

AUFRAEUMEN = Path(__file__).resolve().parent.parent / "aufraeumen"
sys.path.insert(0, str(AUFRAEUMEN))
import protokoll as P       # noqa: E402
import rueckgaengig as R    # noqa: E402

_sperre = threading.Lock()


def _junction(p):
    """Windows-Verbindung: os.walk ginge sonst hinein, in jeder Python-Fassung. OneDrive-Ordner zählen nicht dazu."""
    try:
        return getattr(os.lstat(p), "st_reparse_tag", 0) == 0xA0000003
    except OSError:
        return False


def _schritte():
    alle = P.lesen()
    weg = {e["zurueck_von"] for e in alle if e.get("art") == "zurueck"} | {e["geloescht_von"] for e in alle if e.get("art") == "geloescht"}
    return [e for e in alle if e.get("art") == "papierkorb" and e["nr"] not in weg]


def _im_papierkorb(p, name="Papierkorb"):
    """Liegt p unterhalb eines Ordners mit diesem Namen (und ist nicht der Ordner selbst)?"""
    p = Path(p).absolute()
    return any(x.name.lower() == name.lower() for x in p.parents)


def _wurzel(p):
    r"""Der Ordner „Papierkorb“, in dem p liegt (z. B. C:\Papierkorb)."""
    for x in Path(p).absolute().parents:
        if x.name.lower() == "papierkorb":
            return x
    return Path(p).absolute().parent


def _bekannte_wurzeln():
    """Papierkörbe, die es gibt, auch wenn das Protokoll noch nichts darin kennt."""
    if os.environ.get("AUFRAEUMEN_PAPIERKORB"):
        W = [Path(os.environ["AUFRAEUMEN_PAPIERKORB"]).expanduser().absolute()]
    elif os.name == "nt":
        W = [Path(f"{b}:\\Papierkorb") for b in string.ascii_uppercase]
    else:
        W = [Path.home() / "Papierkorb"]
    return [w for w in W if w.is_dir()]


_system = {"t": 0, "bytes": None}


def _windows_papierkorb():
    r"""Größe des Windows-Papierkorbs dieses Benutzers über alle Laufwerke (X:\$Recycle.Bin\<SID>). Nur Windows,
    höchstens einmal pro Minute gemessen. None, wenn es nicht geht."""
    if os.name != "nt":
        return None
    if time.time() - _system["t"] < 60:
        return _system["bytes"]
    n = None
    try:
        sid = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip().split(",")[-1].strip('"')
        if sid.startswith("S-1-"):
            n = 0
            for b in string.ascii_uppercase:
                d = Path(f"{b}:\\$Recycle.Bin") / sid
                if d.is_dir():
                    for wurzel, unter, dateien in os.walk(d):
                        unter[:] = [x for x in unter if not _junction(os.path.join(wurzel, x))]
                        for f in dateien:
                            if not f.startswith("$I"):   # $I… sind nur die kleinen Begleitdateien
                                try:
                                    n += os.lstat(os.path.join(wurzel, f)).st_size
                                except OSError:
                                    pass
    except (OSError, subprocess.SubprocessError):
        n = None
    _system.update(t=time.time(), bytes=n)
    return n


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
    orte = {}
    for w in _bekannte_wurzeln():
        orte[str(w)] = []
    for e in E:
        orte.setdefault(str(_wurzel(e["nach"])), []).append(e)
    O = [{"key": w, "titel": w, "pfad": w, "eintraege": L, "bytes": sum(x["bytes"] for x in L if x["da"])} for w, L in sorted(orte.items())]
    O.append({"key": "notizen", "titel": "Notizen", "pfad": str(notizen.PAPIERKORB), "notizen": True, "eintraege": N, "bytes": sum(x["bytes"] for x in N)})
    win = _windows_papierkorb()
    return {"orte": O, "windows_bytes": win, "eintraege": E, "notizen": N,
            "bytes": sum(o["bytes"] for o in O) + (win or 0)}


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
    """Endgültig löschen (nur der Besitzer, siehe app.py). b: {nr} | {notiz} | {alles: <key eines Abschnitts>} | {windows: true}."""
    if b.get("windows"):
        if os.name != "nt":
            raise ValueError("Den Windows-Papierkorb gibt es nur unter Windows.")
        r = subprocess.run(["powershell", "-NoProfile", "-Command", "Clear-RecycleBin -Force -ErrorAction Stop"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=300, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        _system["t"] = 0
        if r.returncode:
            raise ValueError("Der Windows-Papierkorb ließ sich nicht leeren: " + (r.stderr.strip()[:200] or "unbekannter Fehler"))
        return {"ok": True}
    if b.get("alles"):
        ort = next((o for o in liste()["orte"] if o["key"] == b["alles"]), None)
        if not ort:
            raise ValueError("Diesen Papierkorb gibt es nicht.")
        fehler = []
        for e in ort["eintraege"]:
            try:
                _loeschen_eins({"notiz": e["pfad"]} if ort.get("notizen") else {"nr": e["nr"]})
            except (ValueError, OSError) as x:
                fehler.append(f"{e['name']}: {x}")
        if fehler:
            raise ValueError("Nicht alles ging: " + "; ".join(fehler)[:400])
        return {"ok": True}
    return _loeschen_eins(b)


def _loeschen_eins(b):
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
