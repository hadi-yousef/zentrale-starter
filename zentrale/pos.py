"""Zentrale: Projekte und Aufgaben (Seite „Projekte“).

Jedes Projekt hat Status (aktiv, ruht, archiv), Orte (Gerät und Pfad), Repos, eine Beschreibung und „Als Nächstes“.
Aufgaben hängen an einem Projekt oder stehen allein, haben ein Fälligkeitsdatum (optional) und gehören dem Besitzer
oder einem Agenten („fuer“). Der Besitzer hakt seine Aufgaben selbst ab, Agenten die eigenen.
Entfernt wird nichts endgültig: Eine entfernte Aufgabe bekommt nur „entfernt“ und ist nicht mehr zu sehen.
Eine Aufgabe kann zu einem Wunsch gehören („wunsch“). Der Wunsch zeigt dann seine Schritte; sind alle erledigt,
hakt die Zentrale den Wunsch selbst ab.

Gespeichert in DATEN/pos.json: {"projekte": [...], "aufgaben": [...]}.
"""
import json
import re
import secrets
import threading
import time

import hub
import wuensche

DATEI = hub.STATE_DIR / "pos.json"
STATUS = ("aktiv", "ruht", "archiv")
FARBEN = ("blue", "green", "orange", "red", "purple", "pink", "teal", "indigo", "cyan", "brown", "gray", "yellow", "mint")
ID = re.compile(r"^[0-9a-f]{6}$")
DATUM = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SYMBOL = re.compile(r"^[a-z0-9-]{1,40}$")
_sperre = threading.Lock()


def _lesen():
    try:
        return json.loads(DATEI.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"projekte": [], "aufgaben": []}
    except (OSError, ValueError):   # nie mit leerer Liste weitermachen, sonst überschreibt das nächste Speichern alles
        raise ValueError("Die Projektliste lässt sich gerade nicht lesen. Es wird nichts überschrieben.")


def _schreiben(d):
    hub.json_schreiben(DATEI, d)


def _text(v, n, pflicht=False):
    t = str(v or "").replace("\r\n", "\n").strip()[:n]
    if pflicht and not t:
        raise ValueError("Text fehlt")
    return t


def stand():
    d = _lesen()
    return {"projekte": d["projekte"], "aufgaben": [a for a in d["aufgaben"] if not a.get("entfernt")]}


def _projekt(d, pid):
    """Projekt per id oder Name (Groß- und Kleinschreibung egal)."""
    pid = str(pid or "").strip()
    p = next((x for x in d["projekte"] if x["id"] == pid), None) if ID.match(pid) else None
    p = p or next((x for x in d["projekte"] if x["name"].lower() == pid.lower()), None)
    if not p:
        raise ValueError("Dieses Projekt gibt es nicht.")
    return p


def _felder_projekt(p, b):
    if "name" in b:
        p["name"] = _text(b["name"], 80, True)
    for k, n in (("beschreibung", 1000), ("naechster_schritt", 300)):
        if k in b:
            p[k] = _text(b[k], n)
    if "status" in b:
        if b["status"] not in STATUS:
            raise ValueError("Status muss aktiv, ruht oder archiv sein.")
        p["status"] = b["status"]
    if "farbe" in b:
        p["farbe"] = b["farbe"] if b["farbe"] in FARBEN else "gray"
    if "symbol" in b:
        p["symbol"] = b["symbol"] if SYMBOL.match(str(b["symbol"] or "")) else "folder"
    if "orte" in b:
        p["orte"] = [{"geraet": _text(o.get("geraet"), 40), "pfad": _text(o.get("pfad"), 300)} for o in (b["orte"] or [])[:10] if isinstance(o, dict)]
    if "repos" in b:
        p["repos"] = [_text(r, 200) for r in (b["repos"] or [])[:10] if _text(r, 200)]


def _wunsch(v):
    """Wunsch als id oder Nummer (3, #3); gespeichert wird immer die id."""
    v = str(v or "").strip().lstrip("#")
    if not v:
        return None
    return wuensche.zeigen(v)["id"]


def projekt_neu(von, b):
    with _sperre:
        d = _lesen()
        if len(d["projekte"]) >= 500:
            raise ValueError("Zu viele Projekte.")
        jetzt = int(time.time())
        p = {"id": secrets.token_hex(3), "name": "", "beschreibung": "", "naechster_schritt": "", "status": "aktiv", "farbe": "gray",
             "symbol": "folder", "orte": [], "repos": [], "von": von, "erstellt": jetzt, "geaendert": jetzt}
        _felder_projekt(p, {"farbe": FARBEN[len(d["projekte"]) % len(FARBEN)], **b})
        if not p["name"]:
            raise ValueError("Name fehlt")
        if any(x["name"].lower() == p["name"].lower() for x in d["projekte"]):
            raise ValueError("Ein Projekt mit diesem Namen gibt es schon.")
        d["projekte"].append(p)
        _schreiben(d)
    return p


def projekt_aendern(von, pid, b):
    with _sperre:
        d = _lesen()
        p = _projekt(d, pid)
        _felder_projekt(p, b)
        p["geaendert"] = int(time.time())
        _schreiben(d)
    return p


def wunsch_pruefen(wid):
    """Sind alle Schritte eines Wunschs erledigt, hakt die Zentrale ihn ab. Kommt danach ein offener Schritt dazu,
    öffnet sie ihn wieder, aber nur, wenn sie ihn selbst abgehakt hat."""
    if not wid:
        return
    with _sperre:
        S = [a for a in _lesen()["aufgaben"] if a.get("wunsch") == wid and not a.get("entfernt")]
    try:
        w = wuensche.zeigen(wid)
    except ValueError:
        return
    if not S:
        return
    fertig = all(a["erledigt"] for a in S)
    if fertig and w["status"] == "offen":
        wuensche.aendern("zentrale", wid, {"status": "erledigt", "ergebnis": ("Alle Schritte erledigt: " + "; ".join(a["titel"] for a in S))[:1900]})
    elif not fertig and w["status"] == "erledigt" and w.get("erledigt_von") == "zentrale":
        wuensche.aendern("zentrale", wid, {"status": "offen"})


def aufgabe_neu(von, b):
    with _sperre:
        d = _lesen()
        if len(d["aufgaben"]) >= 10000:
            raise ValueError("Zu viele Aufgaben.")
        pid = str(b.get("projekt") or "")
        if pid:
            p = _projekt(d, pid)
            pid, p["geaendert"] = p["id"], int(time.time())
        f = str(b.get("faellig") or "")
        if f and not DATUM.match(f):
            raise ValueError("Fällig bitte als JJJJ-MM-TT.")
        a = {"id": secrets.token_hex(3), "titel": _text(b.get("titel"), 200, True), "notiz": _text(b.get("notiz"), 2000), "projekt": pid or None,
             "faellig": f or None, "fuer": _text(b.get("fuer") or von, 40), "wunsch": _wunsch(b.get("wunsch")), "von": von,
             "erstellt": int(time.time()), "erledigt": None, "erledigt_von": ""}
        d["aufgaben"].append(a)
        _schreiben(d)
    wunsch_pruefen(a.get("wunsch"))
    return a


def aufgabe_aendern(von, aid, b):
    alter_wunsch = None
    with _sperre:
        d = _lesen()
        a = next((x for x in d["aufgaben"] if x["id"] == aid and not x.get("entfernt")), None) if ID.match(aid or "") else None
        if not a:
            raise ValueError("Diese Aufgabe gibt es nicht.")
        if "titel" in b:
            a["titel"] = _text(b["titel"], 200, True)
        if "notiz" in b:
            a["notiz"] = _text(b["notiz"], 2000)
        if "faellig" in b:
            f = str(b["faellig"] or "")
            if f and not DATUM.match(f):
                raise ValueError("Fällig bitte als JJJJ-MM-TT.")
            a["faellig"] = f or None
        if "projekt" in b:
            pid = str(b["projekt"] or "")
            a["projekt"] = _projekt(d, pid)["id"] if pid else None
        if "wunsch" in b:
            alter_wunsch = a.get("wunsch")
            a["wunsch"] = _wunsch(b["wunsch"])
        if "erledigt" in b:
            a["erledigt"], a["erledigt_von"] = (int(time.time()), von) if b["erledigt"] else (None, "")
        if b.get("entfernen"):
            if von not in (hub.BESITZER, a["von"]):
                raise PermissionError("Entfernen darf nur der Besitzer oder wer die Aufgabe angelegt hat.")
            a["entfernt"] = int(time.time())
        if a.get("projekt"):
            p = next((x for x in d["projekte"] if x["id"] == a["projekt"]), None)
            if p:
                p["geaendert"] = int(time.time())
        _schreiben(d)
    if alter_wunsch and alter_wunsch != a.get("wunsch"):
        wunsch_pruefen(alter_wunsch)
    wunsch_pruefen(a.get("wunsch"))
    return a
