"""Gemeinsamer Teil von verschieben.py und rueckgaengig.py: Protokoll, Prüfsummen, Platten und Papierkorb.

Jeder Schritt steht als eine Zeile JSON in aufraeumen/protokoll.jsonl (oder AUFRAEUMEN_PROTOKOLL):
  {"nr": 1, "zeit": "…", "art": "verschieben" | "papierkorb" | "zurueck" | "geloescht", "von": "…", "nach": "…", "typ": "datei" | "ordner",
   "bytes": 123, "dateien": 1, "sha256": "…" (nur Dateien unter 100 MB), "grund": "…", "zurueck_von": 7 (nur bei „zurueck“),
   "geloescht_von": 7 (nur bei „geloescht“: der Besitzer hat Schritt 7 in der Zentrale endgültig aus dem Papierkorb gelöscht)}
Die Datei wird nur ergänzt, nie umgeschrieben.
"""
import datetime
import hashlib
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path

HIER = Path(__file__).resolve().parent
PROTOKOLL = Path(os.environ.get("AUFRAEUMEN_PROTOKOLL") or HIER / "protokoll.jsonl")
GRENZE_PRUEFSUMME = 100 * 1024 * 1024
WINDOWS = os.name == "nt"
PY = "py" if WINDOWS else "python3"


class Kaputt(ValueError):
    """Das Protokoll lässt sich nicht lesen (z. B. eine halb geschriebene letzte Zeile)."""


def lesen():
    try:
        zeilen = PROTOKOLL.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    alle = []
    for i, z in enumerate(zeilen, 1):
        if not z.strip():
            continue
        try:
            e = json.loads(z)
        except ValueError:
            e = None
        if not isinstance(e, dict) or not isinstance(e.get("nr"), int):
            raise Kaputt(f"Das Protokoll {PROTOKOLL} ist in Zeile {i} kaputt. Es wurde nichts verändert. "
                         f"Bitte die Zeile ansehen und von Hand reparieren (vorher eine Kopie der Datei machen).")
        alle.append(e)
    return alle


@contextmanager
def sperre():
    """Nur ein Schritt gleichzeitig (z. B. zwei Agenten in zwei Threads). Geht auf Windows, Mac und Linux:
    die Sperrdatei wird exklusiv angelegt; ist sie älter als 10 Minuten, gilt sie als liegengeblieben."""
    datei = PROTOKOLL.with_name(PROTOKOLL.name + ".sperre")
    PROTOKOLL.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(600):
        try:
            os.close(os.open(datei, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            break
        except FileExistsError:
            try:
                if time.time() - datei.stat().st_mtime > 600:
                    datei.unlink()   # liegengebliebene Sperre, erzeugt sich selbst neu
                    continue
            except OSError:
                pass
            time.sleep(0.1)
    else:
        raise SystemExit(f"Ein anderer Schritt läuft gerade (Sperre {datei}). Bitte warten.")
    try:
        # erst prüfen, ob sich das Protokoll lesen lässt, dann ändern: sonst wäre etwas verschoben, ohne Weg zurück
        try:
            lesen()
        except Kaputt as e:
            raise SystemExit(str(e))
        yield
    finally:
        try:
            datei.unlink()
        except OSError:
            pass


def eintragen(eintrag):
    """Aufrufen, während sperre() gehalten wird. Schreibt immer UTF-8 mit \\n, auch unter Windows."""
    alle = lesen()
    eintrag = {"nr": (alle[-1]["nr"] + 1) if alle else 1, "zeit": datetime.datetime.now().isoformat(timespec="seconds"), **eintrag}
    with open(PROTOKOLL, "ab") as f:
        f.write((json.dumps(eintrag, ensure_ascii=False) + "\n").encode("utf-8"))
        f.flush()
        os.fsync(f.fileno())
    return eintrag


def nur_online(st):
    """Liegt die Datei nur in der Cloud (OneDrive „Dateien bei Bedarf“, iCloud „Speicher optimieren“)? Dann würde Lesen sie
    erst herunterladen und die Platte füllen. Solche Dateien werden nie gelesen, nur gezählt."""
    attr = getattr(st, "st_file_attributes", 0)   # Windows
    if attr & (0x400000 | 0x40000 | 0x1000):        # RECALL_ON_DATA_ACCESS, RECALL_ON_OPEN, OFFLINE
        return True
    return bool(getattr(st, "st_flags", 0) & 0x40000000)   # Mac: SF_DATALESS


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for stueck in iter(lambda: f.read(1024 * 1024), b""):
            h.update(stueck)
    return h.hexdigest()


def messen(p):
    """Typ, Größe und Anzahl Dateien; bei Dateien unter 100 MB auch die Prüfsumme. Links werden nicht verfolgt."""
    p = Path(p)
    if p.is_symlink() or p.is_file():
        st = p.lstat()
        lesen_ok = not p.is_symlink() and st.st_size < GRENZE_PRUEFSUMME and not nur_online(st)
        return {"typ": "datei", "bytes": st.st_size, "dateien": 1, "sha256": sha256(p) if lesen_ok else None}
    n = b = 0
    for d, dirs, files in os.walk(p):
        dirs[:] = [x for x in dirs if not _junction(os.path.join(d, x))]
        for f in files:
            try:
                b += os.lstat(os.path.join(d, f)).st_size
                n += 1
            except OSError:
                pass
    return {"typ": "ordner", "bytes": b, "dateien": n, "sha256": None}


def _junction(p):
    """Windows-Verbindung: os.walk ginge sonst hinein, in jeder Python-Fassung. OneDrive-Ordner zählen nicht dazu."""
    try:
        return getattr(os.lstat(p), "st_reparse_tag", 0) == 0xA0000003
    except OSError:
        return False


def platte(p):
    """Kennung der Platte (st_dev) des Pfads oder seines nächsten vorhandenen Elternordners."""
    p = Path(p).absolute()
    while not p.exists():
        p = p.parent
    return p.stat().st_dev


def papierkorb_fuer(p):
    """Papierkorb auf derselben Platte. Windows: <Laufwerk>:\\Papierkorb (z. B. C:\\Papierkorb). Mac und Linux: im
    Benutzerordner ~/Papierkorb, sonst <Wurzel der Platte>/Papierkorb.
    AUFRAEUMEN_PAPIERKORB legt ihn fest (muss auf derselben Platte liegen)."""
    if os.environ.get("AUFRAEUMEN_PAPIERKORB"):
        return Path(os.environ["AUFRAEUMEN_PAPIERKORB"]).expanduser().absolute()
    p, home = Path(p).absolute(), Path.home().absolute()
    if WINDOWS:
        return Path(p.anchor) / "Papierkorb"
    if (home == p or home in p.parents) and platte(home) == platte(p):
        return home / "Papierkorb"
    wurzel = p
    while wurzel.parent != wurzel and platte(wurzel.parent) == platte(p):
        wurzel = wurzel.parent
    return wurzel / "Papierkorb"


def frei(ziel):
    """Freien Namen finden: „name (2).ext“, wenn es das Ziel schon gibt."""
    ziel, n = Path(ziel), 2   # Großschreibung egal (Windows, Mac): exists() sieht das schon richtig
    kandidat = ziel
    while kandidat.exists() or kandidat.is_symlink():
        kandidat = ziel.with_name(f"{ziel.stem} ({n}){ziel.suffix}")
        n += 1
    return kandidat


def groesse(b):
    for einheit, f in (("GB", 1e9), ("MB", 1e6), ("kB", 1e3)):
        if b >= f:
            return f"{b / f:.1f} {einheit}".replace(".", ",")
    return f"{b} Byte"
