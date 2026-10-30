"""Zentrale: Wünsche des Besitzers (Seite „Wünsche“).

Alles, was der Besitzer haben will, steht hier als Punkt. Die Agenten tragen jeden neuen Wunsch ein, immer mit Priorität,
und haken ihn ab, sobald er erledigt ist, mit einem Satz zum Ergebnis. Den Zwischenstand halten sie als Notiz am Wunsch
fest („Stand: … · Als Nächstes: … · Wartet auf: …“).

Gespeichert in DATEN/wuensche.json:
  {"wuensche": [{id, nr, titel, text, von, erstellt, status (offen|erledigt|verworfen), erledigt, erledigt_von, ergebnis,
                 prio (hoch|mittel|niedrig|""), gruppe, notizen: [{id, text, von, zeit}]}]}
Jeder Wunsch hat eine fortlaufende Nummer „nr“. Überall, wo eine id erwartet wird, geht auch die Nummer.
Offene Wünsche stehen nach Priorität (hoch zuerst), innerhalb einer Stufe der neueste oben.
"""
import json
import re
import secrets
import threading
import time

import hub

DATEI = hub.STATE_DIR / "wuensche.json"
STATUS = ("offen", "erledigt", "verworfen")
PRIO = ("hoch", "mittel", "niedrig", "")
ID = re.compile(r"^[0-9a-f]{6}$")
_sperre = threading.Lock()


def _lesen():
    try:
        return json.loads(DATEI.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"wuensche": []}
    except (OSError, ValueError):   # nie mit leerer Liste weitermachen, sonst überschreibt das nächste Speichern alles
        raise ValueError("Die Wunschliste lässt sich gerade nicht lesen. Es wird nichts überschrieben.")


def _schreiben(d):
    hub.json_schreiben(DATEI, d)


def _text(v, n, pflicht=False):
    t = str(v or "").replace("\r\n", "\n").strip()[:n]
    if pflicht and not t:
        raise ValueError("Text fehlt")
    return t


def liste():
    """Offene zuerst (nach Priorität, dann neueste oben), darunter Erledigtes und Verworfenes (zuletzt erledigt oben)."""
    W = _lesen()["wuensche"]
    offen = sorted((w for w in W if w["status"] == "offen"), key=lambda w: (PRIO.index(w.get("prio") or ""), -w["erstellt"]))
    fertig = sorted((w for w in W if w["status"] != "offen"), key=lambda w: -(w.get("erledigt") or w["erstellt"]))
    return {"offen": offen, "erledigt": fertig}


def _finden(d, wid):
    wid = str(wid or "").strip().lstrip("#")
    if wid.isdigit() and len(wid) < 6:
        w = next((x for x in d["wuensche"] if x.get("nr") == int(wid)), None)
    else:
        w = next((x for x in d["wuensche"] if x["id"] == wid), None) if ID.match(wid) else None
    if not w:
        raise ValueError("Diesen Wunsch gibt es nicht.")
    return w


def zeigen(wid):
    return _finden(_lesen(), wid)


def _prio(v, pflicht=False):
    v = str(v or "")
    if v not in PRIO:
        raise ValueError("Priorität muss hoch, mittel oder niedrig sein.")
    if pflicht and not v:
        raise ValueError("Jeder Wunsch braucht eine Priorität: hoch, mittel oder niedrig.")
    return v


def neu(von, b):
    with _sperre:
        d = _lesen()
        if len(d["wuensche"]) >= 5000:
            raise ValueError("Zu viele Wünsche gespeichert.")
        w = {"id": secrets.token_hex(3), "nr": max([x.get("nr") or 0 for x in d["wuensche"]] + [0]) + 1,
             "titel": _text(b.get("titel"), 200, True), "text": _text(b.get("text"), 3000), "von": von,
             "erstellt": int(time.time()), "status": "offen", "erledigt": None, "erledigt_von": "", "ergebnis": "",
             "prio": _prio(b.get("prio"), pflicht=True), "gruppe": _text(b.get("gruppe"), 40), "notizen": []}
        d["wuensche"].append(w)
        _schreiben(d)
    return w


def aendern(von, wid, b):
    """Status setzen (erledigt mit Ergebnis, verworfen mit Begründung, offen zum Zurückholen), Titel, Text oder Priorität ändern."""
    with _sperre:
        d = _lesen()
        w = _finden(d, wid)
        if "titel" in b:
            w["titel"] = _text(b["titel"], 200, True)
        if "text" in b:
            w["text"] = _text(b["text"], 3000)
        if "prio" in b:
            w["prio"] = _prio(b["prio"])
        if "gruppe" in b:
            w["gruppe"] = _text(b["gruppe"], 40)
        st = b.get("status")
        if st is not None:
            if st not in STATUS:
                raise ValueError("Status muss offen, erledigt oder verworfen sein.")
            w["status"] = st
            w["erledigt"], w["erledigt_von"] = (int(time.time()), von) if st != "offen" else (None, "")
            w["ergebnis"] = _text(b.get("ergebnis"), 2000) if st != "offen" else ""
        _schreiben(d)
    return w


def notiz(von, wid, b):
    with _sperre:
        d = _lesen()
        w = _finden(d, wid)
        if len(w["notizen"]) >= 300:
            raise ValueError("Zu viele Notizen an diesem Wunsch.")
        w["notizen"].append({"id": secrets.token_hex(3), "text": _text(b.get("text"), 4000, True), "von": von, "zeit": int(time.time())})
        _schreiben(d)
    return w


def notiz_loeschen(von, wid, nid):
    """Eine Notiz entfernen. Das darf ihr Verfasser und der Besitzer."""
    with _sperre:
        d = _lesen()
        w = _finden(d, wid)
        n = next((x for x in w["notizen"] if x["id"] == nid), None)
        if not n:
            raise ValueError("Diese Notiz gibt es nicht.")
        if von not in (hub.BESITZER, n["von"]):
            raise PermissionError("Nur der Besitzer oder wer die Notiz geschrieben hat, darf sie entfernen.")
        w["notizen"].remove(n)
        _schreiben(d)
    return w
