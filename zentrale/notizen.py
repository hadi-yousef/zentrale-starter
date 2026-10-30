"""Zentrale: Notizen (Seite „Notizen“).

Die Notizen sind einfache Markdown-Dateien in einem Ordner (Standard: DATEN/notizen, sonst ZENTRALE_NOTIZEN).
Sie lassen sich auch mit Obsidian oder jedem Texteditor öffnen; die Zentrale zeigt, sucht und bearbeitet dieselben Dateien.
Ordner sind frei; Notizen unter Projekte/<Name>/ gehören zu diesem Projekt.
Versteckte Dateien und Ordner (.obsidian, .DS_Store) bleiben außen vor.
Entfernen löscht nie: Die Datei wandert in den versteckten Ordner .papierkorb/<datum>/ im Notizen-Ordner (gleiche Platte,
kostet keinen Platz). Leeren tut nur der Besitzer.
"""
import os
import re
import threading
import time
import unicodedata
from pathlib import Path

import hub

WURZEL = Path(os.environ.get("ZENTRALE_NOTIZEN") or hub.STATE_DIR / "notizen")
PAPIERKORB = WURZEL / ".papierkorb"
MAX_TEXT = 512 * 1024
_sperre = threading.Lock()
_kopf = {}   # pfad -> (mtime_ns, size, kopfdaten), damit nicht jede Liste alle Dateien liest


def _sicher(rel):
    """Relativen Pfad prüfen: nur .md unterhalb der Wurzel, keine versteckten Teile, kein '..'."""
    rel = str(rel or "").replace("\\", "/").strip("/")
    teile = rel.split("/")
    # „:“ ist auch verboten, weil „a:b.md“ unter Windows ein versteckter Datenstrom der Datei „a“ wäre
    if not rel or len(rel) > 400 or any(not t or t.startswith(".") or t == ".." or VERBOTEN.search(t) for t in teile) or not rel.lower().endswith(".md"):
        raise ValueError("Ungültiger Pfad")
    p = (WURZEL / rel).resolve()
    if WURZEL.resolve() not in p.parents:
        raise ValueError("Ungültiger Pfad")
    return rel, p


# Unter Windows verboten: diese Zeichen, Steuerzeichen, Namen wie CON oder NUL, Punkt oder Leerzeichen am Ende
VERBOTEN = re.compile(r'[<>:"|?*\x00-\x1f]')
RESERVIERT = re.compile(r"^(con|prn|aux|nul|com\d|lpt\d)(\..*)?$", re.I)


def _name_ok(t):
    return bool(t) and not t.startswith(".") and t != ".." and not VERBOTEN.search(t) and not RESERVIERT.match(t) and t == t.rstrip(" .")


def _ordner_sicher(ordner):
    ordner = str(ordner or "").replace("\\", "/").strip("/")
    if ordner and (len(ordner) > 300 or not all(_name_ok(t) for t in ordner.split("/"))):
        raise ValueError("Ungültiger Ordner (nicht erlaubt: < > : \" | ? *, Namen wie CON, Punkt am Ende)")
    return ordner


def _titel_und_vorschau(text, rel):
    titel, rest = "", []
    zeilen = text.splitlines()
    if zeilen and zeilen[0].strip() == "---":   # Frontmatter (Obsidian) überspringen
        ende = next((i for i, z in enumerate(zeilen[1:], 1) if z.strip() == "---"), 0)
        zeilen = zeilen[ende + 1:] if ende else zeilen
    for z in zeilen:
        s = z.strip()
        if not titel and s.startswith("# "):
            titel = s[2:].strip()
        elif s:
            rest.append(re.sub(r"[#*_`>\[\]]", "", s))
        if titel and len(" ".join(rest)) > 220:
            break
    return titel or Path(rel).stem, " ".join(rest)[:220]


def _info(rel, p, st):
    k = _kopf.get(rel)
    if not k or k[0] != st.st_mtime_ns or k[1] != st.st_size:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")[:20000]
        except OSError:
            text = ""
        k = (st.st_mtime_ns, st.st_size, _titel_und_vorschau(text, rel))
        _kopf[rel] = k
    titel, vorschau = k[2]
    ordner = rel.rsplit("/", 1)[0] if "/" in rel else ""
    return {"pfad": rel, "ordner": ordner, "titel": titel, "vorschau": vorschau, "bytes": st.st_size, "zeit": int(st.st_mtime)}


def liste():
    """Alle Notizen, die zuletzt geänderte zuerst, dazu alle Ordner."""
    N, ordner = [], set()
    WURZEL.mkdir(parents=True, exist_ok=True)
    for d, dirs, files in os.walk(WURZEL):
        dirs[:] = [x for x in dirs if not x.startswith(".")]
        relord = os.path.relpath(d, WURZEL)
        if relord != ".":
            ordner.add(relord.replace(os.sep, "/"))
        for f in files:
            if f.startswith(".") or not f.lower().endswith(".md"):
                continue
            p = Path(d) / f
            try:
                st = p.stat()
            except OSError:
                continue
            N.append(_info(str(p.relative_to(WURZEL)).replace(os.sep, "/"), p, st))
    N.sort(key=lambda n: -n["zeit"])
    return {"notizen": N, "ordner": sorted(ordner)}


def lesen(rel):
    rel, p = _sicher(rel)
    try:
        st = p.stat()
        text = p.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        raise ValueError("Diese Notiz gibt es nicht (mehr).")
    return {**_info(rel, p, st), "text": text, "version": str(st.st_mtime_ns)}


def _dateiname(titel):
    s = unicodedata.normalize("NFC", str(titel or "").strip())
    s = re.sub(r'[\\/:*?"<>|#^\[\]\x00-\x1f]', " ", s)
    s = re.sub(r"\s+", " ", s)[:80].strip(" .")
    if RESERVIERT.match(s):
        s = "Notiz " + s
    return s or time.strftime("Notiz %Y-%m-%d %H-%M")


def speichern(rel, text, version):
    """Eine vorhandene Notiz überschreiben. version ist der Stand beim Öffnen; hat sie jemand anders inzwischen geändert
    (z. B. im Editor), wird nicht überschrieben."""
    text = str(text or "").replace("\r\n", "\n")
    if len(text.encode()) > MAX_TEXT:
        raise ValueError("Die Notiz ist zu groß (höchstens 512 KB).")
    rel, p = _sicher(rel)
    with _sperre:
        try:
            jetzt = str(p.stat().st_mtime_ns)
        except FileNotFoundError:
            raise ValueError("Diese Notiz gibt es nicht mehr.")
        if str(version or "") != jetzt:
            raise ValueError("Die Notiz wurde inzwischen woanders geändert. Bitte neu öffnen, dein Text bleibt im Feld stehen.")
        tmp = p.with_name("." + p.name + ".zentrale-tmp")
        tmp.write_bytes(text.encode("utf-8"))   # immer UTF-8 und \n, auch unter Windows
        tmp.replace(p)
    return lesen(rel)


def neu(ordner, titel, text=""):
    ordner = _ordner_sicher(ordner)
    name = _dateiname(titel)
    with _sperre:
        d = WURZEL / ordner if ordner else WURZEL
        d.mkdir(parents=True, exist_ok=True)
        p, n = d / f"{name}.md", 2
        while p.exists():
            p, n = d / f"{name} {n}.md", n + 1
        inhalt = str(text or "").replace("\r\n", "\n")
        if not inhalt.lstrip().startswith("# "):
            inhalt = f"# {str(titel or name).strip()}\n\n{inhalt}"
        if len(inhalt.encode()) > MAX_TEXT:
            raise ValueError("Die Notiz ist zu groß (höchstens 512 KB).")
        p.write_bytes(inhalt.encode("utf-8"))
    return lesen(str(p.relative_to(WURZEL)).replace(os.sep, "/"))


def suche(q, n=50):
    """Volltextsuche: alle Wörter müssen vorkommen. Treffer im Titel zählen mehr. Gibt Ausschnitte um den ersten Treffer."""
    woerter = [w for w in re.split(r"\s+", str(q or "").lower().strip()) if w][:8]
    if not woerter:
        return []
    T = []
    for info in liste()["notizen"]:
        try:
            text = (WURZEL / info["pfad"]).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        klein, tit = text.lower(), info["titel"].lower()
        if not all(w in klein or w in tit or w in info["pfad"].lower() for w in woerter):
            continue
        punkte = sum(5 * tit.count(w) + min(klein.count(w), 20) for w in woerter)
        i = min((klein.find(w) for w in woerter if w in klein), default=0)
        a = max(0, i - 80)
        stueck = re.sub(r"\s+", " ", text[a:a + 240]).strip()
        T.append({**info, "punkte": punkte, "ausschnitt": ("… " if a else "") + stueck + " …"})
    T.sort(key=lambda t: (-t["punkte"], -t["zeit"]))
    return T[:n]


def in_papierkorb(rel, von):
    """Die Datei in den Papierkorb verschieben (im Notizen-Ordner, also gleiche Platte). Gelöscht wird nichts."""
    rel, p = _sicher(rel)
    if not p.is_file():
        raise ValueError("Diese Notiz gibt es nicht (mehr).")
    with _sperre:
        ziel = PAPIERKORB / time.strftime("%Y-%m-%d") / rel
        ziel.parent.mkdir(parents=True, exist_ok=True)
        n = 2
        while ziel.exists():
            ziel, n = ziel.with_name(f"{Path(rel).stem} ({n}).md"), n + 1
        os.replace(p, ziel)
    return {"ok": True, "papierkorb": str(ziel.relative_to(WURZEL)).replace(os.sep, "/")}
