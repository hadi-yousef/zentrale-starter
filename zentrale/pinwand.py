"""Zentrale: Pinwand eines Projekts (wie im Vorbild, „Freie Wand“).

Karten (Titel, Text, Gruppe, Marke, Position, dazu optional Farbe, Größe, Symbol, Mindesthöhe) liegen frei auf einer Wand. Die Gruppen ergeben sich aus den Karten:
Der Rahmen mit Titel wird in der Oberfläche aus den Karten einer Gruppe berechnet.
Entfernt wird nichts endgültig: Eine entfernte Karte bekommt nur „entfernt“ und bleibt in den Daten.
Das Projekt bekommt beim ersten Pin das Feld „pinwand“ (bleibt). Die Oberfläche öffnet die Wand aus dem Projektblatt im Vollbild.
Rechte: der Besitzer und alle Agenten, keine Geräte-Schlüssel (die dürfen nur melden, siehe app.py).

Gespeichert in DATEN/pinwand.json: {"pins": [...]}. Schnittstelle in app.py (/api/pinwand/<projekt-id>/…).
"""
import json
import math
import re
import threading
import time

import hub
import pos

DATEI = hub.STATE_DIR / "pinwand.json"
ID = re.compile(r"^[0-9a-f]{6}$")
GRENZE = {"titel": 120, "text": 2000, "gruppe": 60, "marke": 30, "symbol": 16}
FARBEN = ("blau", "gruen", "orange", "rot", "lila", "gelb", "grau")   # leer = Standard
GROESSEN = ("S", "M", "L")
H_MIN, H_MAX = 40, 1200
MAX_AKTIV = 300     # sichtbare Karten je Projekt
MAX_ALLE = 1000     # mit entfernten Karten je Projekt
MAX_GESAMT = 5000   # alle Projekte zusammen
POS_MIN, POS_MAX = 0, 5000
B_MIN, B_MAX, B_STD = 120, 480, 190
_sperre = threading.Lock()


def _lesen():
    try:
        return json.loads(DATEI.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"pins": []}
    except (OSError, ValueError):   # nie mit leerer Liste weitermachen, sonst überschreibt das nächste Speichern alles
        raise ValueError("Die Pinwand lässt sich gerade nicht lesen. Es wird nichts überschrieben.")


def _schreiben(d):
    hub.json_schreiben(DATEI, d)


def _text(v, name, pflicht=False):
    if v is not None and not isinstance(v, (str, int, float)) or isinstance(v, bool):
        raise ValueError(f"{name}: bitte Text")
    t = str(v if v is not None else "").replace("\r\n", "\n").strip()
    if len(t) > GRENZE[name]:
        raise ValueError(f"{name.capitalize()} ist zu lang (höchstens {GRENZE[name]} Zeichen).")
    if pflicht and not t:
        raise ValueError("Titel fehlt" if name == "titel" else f"{name.capitalize()} fehlt")
    return t


def _zahl(v, name, lo, hi):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        if isinstance(v, str):
            try:
                v = float(v.replace(",", "."))
            except ValueError:
                raise ValueError(f"{name} muss eine Zahl sein.")
        else:
            raise ValueError(f"{name} muss eine Zahl sein.")
    if not math.isfinite(v) or v < lo or v > hi:
        raise ValueError(f"{name} muss zwischen {lo} und {hi} liegen.")
    return int(round(v))


def _gestalt(b):
    """Die neuen optionalen Felder (Farbe, Größe, Symbol, Mindesthöhe) aus der Eingabe prüfen. Leer oder null heißt: Feld entfernen (Standard).
    Rückgabe: {feld: wert oder None}; None bedeutet entfernen."""
    e = {}
    if "farbe" in b:
        v = b["farbe"]
        if v in (None, ""):
            e["farbe"] = None
        elif v in FARBEN:
            e["farbe"] = v
        else:
            raise ValueError("Farbe: erlaubt sind " + ", ".join(FARBEN) + ".")
    if "groesse" in b:
        v = b["groesse"]
        if v in (None, ""):
            e["groesse"] = None
        elif v in GROESSEN:
            e["groesse"] = v
        else:
            raise ValueError("Größe: erlaubt sind S, M und L.")
    if "symbol" in b:
        e["symbol"] = _text(b["symbol"], "symbol") or None
    if "h" in b:
        e["h"] = None if b["h"] in (None, "") else _zahl(b["h"], "Höhe", H_MIN, H_MAX)
    return e


def _gestalt_setzen(p, e):
    for k, v in e.items():
        if v is None:
            p.pop(k, None)
        else:
            p[k] = v


def _projekt_ok(pid):
    d = pos._lesen()
    if not ID.match(pid or "") or not any(p["id"] == pid for p in d["projekte"]):
        raise ValueError("Dieses Projekt gibt es nicht.")


def _markieren(pid):
    """Das Feld „pinwand“ am Projekt setzen (einmal, bleibt)."""
    with pos._sperre:
        d = pos._lesen()
        p = next((x for x in d["projekte"] if x["id"] == pid), None)
        if p and not p.get("pinwand"):
            p["pinwand"] = {"seit": int(time.time())}
            pos._schreiben(d)


def _sichtbar(d, pid):
    return [p for p in d["pins"] if p["projekt"] == pid and not p.get("entfernt")]


def _hoehe(p):
    """Grobe Höhe einer Karte (die Oberfläche kennt die wirkliche)."""
    zeilen = max(1, math.ceil(len(p.get("text") or "") / max(8, (p.get("b") or B_STD) / 7.0)))
    return max(64 + 18 * zeilen + (20 if p.get("marke") else 0), p.get("h") or 0)


def _frei(pins, gruppe, b, h):
    """Freier Platz in der Gruppe (sonst unter allem), ohne eine andere Karte oder fremde Gruppe zu überdecken."""
    gap = 12
    eigene = [p for p in pins if p["gruppe"] == gruppe]
    sperr = [(p["x"], p["y"], p["x"] + (p.get("b") or B_STD), p["y"] + _hoehe(p)) for p in pins if p["gruppe"] != gruppe]
    fremd = {}
    for p in pins:
        if p["gruppe"] != gruppe:
            r = fremd.setdefault(p["gruppe"], [10 ** 9, 10 ** 9, -1, -1])
            r[0], r[1] = min(r[0], p["x"]), min(r[1], p["y"])
            r[2], r[3] = max(r[2], p["x"] + (p.get("b") or B_STD)), max(r[3], p["y"] + _hoehe(p))
    rahmen = [(r[0] - 18, r[1] - 46, r[2] + 18, r[3] + 18) for r in fremd.values()]
    belegt = [(p["x"], p["y"], p["x"] + (p.get("b") or B_STD), p["y"] + _hoehe(p)) for p in eigene]

    def passt(x, y, innen):
        r = (x, y, x + b, y + h)
        for a in belegt + sperr:
            if r[0] < a[2] + gap and a[0] < r[2] + gap and r[1] < a[3] + gap and a[1] < r[3] + gap:
                return False
        for a in rahmen:
            if r[0] < a[2] and a[0] < r[2] and r[1] < a[3] and a[1] < r[3]:
                return False
        return True

    if eigene:
        x0 = min(p["x"] for p in eigene)
        y0 = min(p["y"] for p in eigene)
        x1 = max(p["x"] + (p.get("b") or B_STD) for p in eigene)
        y1 = max(p["y"] + _hoehe(p) for p in eigene)
        for y in range(y0, y1 + 1, 10):
            for x in range(x0, max(x0, x1 - b) + 1, 10):
                if passt(x, y, True):
                    return x, y
        y = y1 + gap
        while y < POS_MAX and not passt(x0, y, False):
            y += 10
        return x0, min(y, POS_MAX)
    # neue Gruppe: links unter allem
    unten = max([a[3] for a in sperr] + [0])
    return 24, min(unten + 60 if sperr else 46, POS_MAX)


def pins(pid, entfernte=False):
    """Sichtbare Karten; auf Wunsch zusätzlich die entfernten dieses Projekts (zuletzt entfernte zuerst) unter „entfernte“."""
    _projekt_ok(pid)
    d = _lesen()
    r = {"pins": _sichtbar(d, pid)}
    if entfernte:
        r["entfernte"] = sorted((p for p in d["pins"] if p["projekt"] == pid and p.get("entfernt")), key=lambda p: -p["entfernt"])
    return r


def _neu(d, von, pid, b):
    if not isinstance(b, dict):
        raise ValueError("Ungültige Eingabe.")
    alle = [p for p in d["pins"] if p["projekt"] == pid]
    if len(_sichtbar(d, pid)) >= MAX_AKTIV or len(alle) >= MAX_ALLE or len(d["pins"]) >= MAX_GESAMT:
        raise ValueError(f"Zu viele Karten (höchstens {MAX_AKTIV} je Projekt).")
    p = {"id": hub.neue_id(d["pins"]), "projekt": pid, "titel": _text(b.get("titel"), "titel", True), "text": _text(b.get("text"), "text"),
         "gruppe": _text(b.get("gruppe"), "gruppe") or "Ohne Gruppe", "marke": _text(b.get("marke"), "marke"),
         "b": _zahl(b["b"], "Breite", B_MIN, B_MAX) if b.get("b") not in (None, "") else B_STD, "von": von}
    _gestalt_setzen(p, _gestalt(b))
    if (b.get("x") in (None, "")) != (b.get("y") in (None, "")):
        raise ValueError("x und y gehören zusammen.")
    if b.get("x") in (None, ""):
        p["x"], p["y"] = _frei(_sichtbar(d, pid), p["gruppe"], p["b"], _hoehe(p))
    else:
        p["x"], p["y"] = _zahl(b["x"], "x", POS_MIN, POS_MAX), _zahl(b["y"], "y", POS_MIN, POS_MAX)
    p["erstellt"] = p["geaendert"] = int(time.time())
    d["pins"].append(p)
    return p


def neu(von, pid, b):
    """Eine Karte (oder mit {"pins": [...]} mehrere auf einmal, alles oder nichts) anpinnen.
    Die Sammelanlage ist wiederholbar: Eine Karte mit gleichem Titel und gleicher Gruppe, die es schon gibt, wird nicht noch einmal
    angelegt (die vorhandene kommt zurück). Zuerst wird alles geprüft, dann das Projekt gekennzeichnet, dann gespeichert: Scheitert ein
    Schritt, ist nichts Halbes entstanden, und derselbe Aufruf lässt sich wiederholen."""
    _projekt_ok(pid)
    liste = b.get("pins") if isinstance(b, dict) and "pins" in b else None
    if liste is not None and (not isinstance(liste, list) or len(liste) > MAX_AKTIV):
        raise ValueError("pins muss eine Liste sein.")
    with _sperre:
        d = _lesen()
        if liste is None:
            ergebnis = [_neu(d, von, pid, b)]
        else:
            ergebnis = []
            for x in liste:
                vorhanden = None
                if isinstance(x, dict):
                    t, g = str(x.get("titel") or "").strip(), (str(x.get("gruppe") or "").strip() or "Ohne Gruppe")
                    vorhanden = next((p for p in _sichtbar(d, pid) if p["titel"] == t and p["gruppe"] == g), None)
                ergebnis.append(vorhanden or _neu(d, von, pid, x))
        _markieren(pid)
        _schreiben(d)
    return ergebnis if liste is not None else ergebnis[0]


def _finden(d, pid, kid):
    p = next((x for x in d["pins"] if x["id"] == kid and x["projekt"] == pid and not x.get("entfernt")), None) if ID.match(kid or "") else None
    if not p:
        raise ValueError("Diese Karte gibt es nicht.")
    return p


def aendern(von, pid, kid, b):
    """Felder ändern, verschieben (x, y, b) oder entfernen ({"entfernen": true}); entfernt wird nur markiert."""
    if not isinstance(b, dict):
        raise ValueError("Ungültige Eingabe.")
    _projekt_ok(pid)
    with _sperre:
        d = _lesen()
        p = _finden(d, pid, kid)
        neu_ = {}
        for k in ("titel", "text", "gruppe", "marke"):
            if k in b:
                neu_[k] = _text(b[k], k, k in ("titel",))
        if "gruppe" in neu_ and not neu_["gruppe"]:
            neu_["gruppe"] = "Ohne Gruppe"
        if ("x" in b) != ("y" in b):
            raise ValueError("x und y gehören zusammen.")
        if "x" in b:
            neu_["x"], neu_["y"] = _zahl(b["x"], "x", POS_MIN, POS_MAX), _zahl(b["y"], "y", POS_MIN, POS_MAX)
        if "b" in b:
            neu_["b"] = _zahl(b["b"], "Breite", B_MIN, B_MAX)
        p.update(neu_)
        _gestalt_setzen(p, _gestalt(b))
        if b.get("entfernen"):
            p["entfernt"] = int(time.time())
            p["entfernt_von"] = von
        p["geaendert"] = int(time.time())
        _schreiben(d)
    return p


def zurueckholen(von, pid, kid):
    """Eine entfernte Karte wieder sichtbar machen (Position und Gestaltung bleiben, wie sie waren)."""
    _projekt_ok(pid)
    with _sperre:
        d = _lesen()
        p = next((x for x in d["pins"] if x["id"] == kid and x["projekt"] == pid and x.get("entfernt")), None) if ID.match(kid or "") else None
        if not p:
            raise ValueError("Diese entfernte Karte gibt es nicht.")
        if len(_sichtbar(d, pid)) >= MAX_AKTIV:
            raise ValueError(f"Zu viele Karten (höchstens {MAX_AKTIV} je Projekt).")
        p.pop("entfernt", None)
        p.pop("entfernt_von", None)
        p["zurueck_von"] = von
        p["geaendert"] = int(time.time())
        _schreiben(d)
    return p


def verschieben(von, pid, b):
    """Mehrere Karten auf einmal verschieben (ganze Gruppe), alles oder nichts: {"pins": [{"id", "x", "y"}, ...]}."""
    liste = b.get("pins") if isinstance(b, dict) else None
    if not isinstance(liste, list) or not liste or len(liste) > MAX_AKTIV:
        raise ValueError("pins muss eine Liste mit Karten sein.")
    _projekt_ok(pid)
    with _sperre:
        d = _lesen()
        neue = []
        for e in liste:
            if not isinstance(e, dict):
                raise ValueError("Ungültige Eingabe.")
            neue.append((_finden(d, pid, e.get("id")), _zahl(e.get("x"), "x", POS_MIN, POS_MAX), _zahl(e.get("y"), "y", POS_MIN, POS_MAX)))
        jetzt = int(time.time())
        for p, x, y in neue:
            p["x"], p["y"], p["geaendert"] = x, y, jetzt
        _schreiben(d)
    return {"pins": [p for p, _, _ in neue]}
