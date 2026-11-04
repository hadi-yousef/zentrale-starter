"""Zentrale: Notizen (Seite „Notizen“).

Die Notizen sind einfache Markdown-Dateien in einem Ordner (Standard: DATEN/notizen, sonst ZENTRALE_NOTIZEN).
Sie lassen sich auch mit Obsidian oder jedem Texteditor öffnen; die Zentrale zeigt, sucht und bearbeitet dieselben Dateien.
Ordner sind frei; Notizen unter Projekte/<Name>/ gehören zu diesem Projekt.
Versteckte Dateien und Ordner (.obsidian, .DS_Store) bleiben außen vor.
Beim ersten Start legt grundgeruest() die festen Ordner mit je einer Startseite an (siehe GRUNDGERUEST, nie überschrieben;
löscht der Besitzer eine davon, kommt sie nicht wieder, dafür sorgt die Merkdatei .grundgeruest).
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
    if not _drin(p):
        raise ValueError("Ungültiger Pfad")
    return rel, p


def _drin(p, ordner_ok=False):
    """Liegt p nach Auflösen aller Verknüpfungen in der Wurzel? (Verknüpfungen nach außen zählen nicht.)"""
    w, p = WURZEL.resolve(), Path(p).resolve()
    return w in p.parents or (ordner_ok and p == w)


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
            if not _drin(p):   # Verknüpfung nach außen: nicht zeigen (wie lesen())
                continue
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


def _titel_ordnen(ordner, titel):
    """„Geräte/Drucker.md“ als Titel: Endung weg, und ein vorhandener Ordner wird zum Ordner. Sonst entstand eine lose Notiz „… .md.md“."""
    t = re.sub(r"\.md$", "", str(titel or "").strip(), flags=re.I).strip()
    teile = [x.strip() for x in re.split(r"[\\/]", t) if x.strip()]
    if not ordner and len(teile) > 1:
        kopf = "/".join(teile[:-1])
        try:
            if (WURZEL / _ordner_sicher(kopf)).is_dir():
                return kopf, teile[-1]
        except ValueError:
            pass
    return ordner, t


def neu(ordner, titel, text=""):
    ordner, titel = _titel_ordnen(ordner, titel)
    ordner = _ordner_sicher(ordner)
    name = _dateiname(titel)
    inhalt = str(text or "").replace("\r\n", "\n")
    if not inhalt.lstrip().startswith("# "):
        inhalt = f"# {str(titel or name).strip()}\n\n{inhalt}"
    if len(inhalt.encode()) > MAX_TEXT:
        raise ValueError("Die Notiz ist zu groß (höchstens 512 KB).")
    with _sperre:
        WURZEL.mkdir(parents=True, exist_ok=True)
        d = WURZEL / ordner if ordner else WURZEL
        # vor dem Anlegen prüfen: führt ein Teil des Ordners über eine Verknüpfung nach außen, wird nichts geschrieben
        if not _drin(d, ordner_ok=True):
            raise ValueError("Ungültiger Ordner (führt aus dem Notizen-Ordner heraus)")
        d.mkdir(parents=True, exist_ok=True)
        if not _drin(d, ordner_ok=True):
            raise ValueError("Ungültiger Ordner (führt aus dem Notizen-Ordner heraus)")
        p, n = d / f"{name}.md", 2
        while os.path.lexists(p):
            p, n = d / f"{name} {n}.md", n + 1
        # O_EXCL: schreibt nie durch eine (auch kaputte) Verknüpfung und nie über eine Datei, die gerade entstanden ist
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0), 0o644)
        with os.fdopen(fd, "wb") as f:
            f.write(inhalt.encode("utf-8"))
    return lesen(str(p.relative_to(WURZEL)).replace(os.sep, "/"))


GRUNDGERUEST = {
    "So funktionieren die Notizen.md": """# So funktionieren die Notizen

Das Gedächtnis von Besitzer und Agenten. Ein Chat vergisst alles, die Notizen nicht. Jede Notiz ist eine Markdown-Datei
in `daten\\notizen`, lesbar mit der Zentrale, mit Obsidian oder jedem Editor.

| Ordner | Was hinein gehört |
|---|---|
| `Besitzer/` | Fakten über den Besitzer: was er sagt, was ihm wichtig ist, wie er arbeitet. Start: `Besitzer/INDEX.md` |
| `Geräte/` | je Gerät eine Notiz: Rechner, Platten, Sticks, Drucker, Router (Modell, Größe, wofür) |
| `Projekte/<Name>/` | was zu einem Projekt gehört und nicht ins Repo passt (Ideen, Entscheidungen, Links) |
| `Aufräumen/` | Inventur, Plan, „So ist es jetzt geordnet“ |
| `Anleitungen/` | wie etwas geht, sobald es einmal geklappt hat (Schritt für Schritt) |
| `Übergaben/` | am Ende jeder längeren Sitzung: was gemacht wurde, was offen ist, wo es weitergeht (eine Notiz je Tag) |

Regeln:
- Nur Fakten, mit Datum und Quelle („Besitzer im Chat, 2.11.“). Nichts raten.
- Nie Passwörter, Schlüssel, Kontonummern oder Gesundheitsdaten.
- Erst suchen (`notiz-suche`), dann ergänzen (`notiz-ergaenzen`), nur wenn es nichts gibt, neu anlegen (`notiz-neu`).
- Wird eine Notiz länger als etwa 200 Zeilen, aufteilen und im INDEX des Ordners verlinken.
""",
    "Besitzer/INDEX.md": """# Besitzer (Wegweiser)

Alles, was Agenten über den Besitzer wissen sollen. **Zuerst diese Seite lesen**, dann nur die Datei öffnen, die man braucht.
Nur Fakten, die er gesagt hat oder die belegt sind, mit Datum und Quelle. Keine Passwörter, Kontonummern, Gesundheitsdaten.

## Steckbrief

| Punkt | Stand | Quelle |
|---|---|---|
| Anrede | | |
| Rechner | | |
| Was ihn am meisten stört | | |
| Was ihm am wichtigsten ist | | |

## Dateien in diesem Ordner

(noch keine)
""",
    "Übergaben/INDEX.md": """# Übergaben

Am Ende jeder längeren Sitzung eine Notiz `Übergaben/<JJJJ-MM-TT>.md` (gibt es sie schon: ergänzen):
was gemacht wurde, was offen ist, worauf gewartet wird, wo der nächste Thread weitermacht. Mit Wunsch-Nummern.
""",
}


def grundgeruest():
    """Feste Ordner mit Startseiten anlegen, einmal (Merkdatei .grundgeruest). Vorhandenes wird nie überschrieben."""
    merk = WURZEL / ".grundgeruest"
    if merk.exists():
        return
    with _sperre:
        for rel, text in GRUNDGERUEST.items():
            p = WURZEL / rel
            if not p.exists():
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(text.encode("utf-8"))
        for ordner in ("Geräte", "Projekte", "Aufräumen", "Anleitungen"):
            (WURZEL / ordner).mkdir(parents=True, exist_ok=True)
        merk.write_text("Grundgerüst angelegt. Diese Datei verhindert, dass gelöschte Startseiten wiederkommen.\n", encoding="utf-8")


def suche(q, n=50):
    """Volltextsuche: alle Wörter müssen vorkommen. Treffer im Titel zählen mehr. Gibt Ausschnitte um den ersten Treffer."""
    woerter = [w for w in re.split(r"\s+", str(q or "").lower().strip()) if w][:8]
    if not woerter:
        return []
    T = []
    for info in liste()["notizen"]:
        try:
            _, p = _sicher(info["pfad"])   # dieselbe Grenze wie beim Lesen
            text = p.read_text(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
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
        if not _drin(ziel.parent, ordner_ok=True):
            raise ValueError("Der Papierkorb der Notizen führt aus dem Notizen-Ordner heraus.")
        ziel.parent.mkdir(parents=True, exist_ok=True)
        n = 2
        while ziel.exists():
            ziel, n = ziel.with_name(f"{Path(rel).stem} ({n}).md"), n + 1
        os.replace(p, ziel)
    return {"ok": True, "papierkorb": str(ziel.relative_to(WURZEL)).replace(os.sep, "/")}
