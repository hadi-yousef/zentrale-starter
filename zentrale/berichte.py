"""Zentrale: Berichte der Agenten an den Besitzer, mit Fragen und Antworten (Seite „Berichte“).

Ein Agent legt einen Bericht an: Titel, kurze Zusammenfassung, ganzer Text (Markdown) und Fragen, gern mit Vorschlägen
(„Ja|Nein“). Der Besitzer sieht die Fragen nacheinander und antwortet mit einem Tipp auf einen Vorschlag oder mit Text.
Der Agent holt die Antworten ab:
  - GET /api/berichte/warten hält die Verbindung offen, bis der Besitzer in einem Bericht dieses Agenten schreibt.
    `zentrale_client.py berichte-warten` wartet so und endet mit den neuen Nachrichten.
  - Mit „sitzung“ kann ein Agent mehrere Chats auseinanderhalten.

Gespeichert in DATEN/berichte.json: {"berichte": [{id, nr, titel, kurz, text, von, sitzung, projekt, wunsch, zeit, gelesen,
  fragen: [{id, text, vorschlaege, antwort}], verlauf: [{id, von, text, zeit, frage, abgeholt}]}]}
Jeder Bericht hat eine fortlaufende Nummer „nr“. Überall, wo eine id erwartet wird, geht auch die Nummer.
"""
import json
import re
import secrets
import threading
import time

import hub

DATEI = hub.STATE_DIR / "berichte.json"
ID = re.compile(r"^[0-9a-f]{6}$")
B = hub.BESITZER
_sperre = threading.Lock()
_neu = threading.Condition(_sperre)


def _lesen():
    try:
        return json.loads(DATEI.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"berichte": []}
    except (OSError, ValueError):
        raise ValueError("Die Berichte lassen sich gerade nicht lesen. Es wird nichts überschrieben.")


def _schreiben(d):
    hub.json_schreiben(DATEI, d)


def _text(v, n, pflicht=False):
    t = str(v or "").replace("\r\n", "\n").strip()[:n]
    if pflicht and not t:
        raise ValueError("Text fehlt")
    return t


def _finden(d, bid):
    bid = str(bid or "").strip().lstrip("#")
    if bid.isdigit() and len(bid) < 6:
        b = next((x for x in d["berichte"] if x.get("nr") == int(bid)), None)
    else:
        b = next((x for x in d["berichte"] if x["id"] == bid), None) if ID.match(bid) else None
    if not b:
        raise ValueError("Diesen Bericht gibt es nicht.")
    return b


def offene_fragen(b):
    return sum(1 for f in b["fragen"] if not f.get("antwort"))


def liste():
    """Neueste zuerst (zählt auch die letzte Nachricht)."""
    with _sperre:
        X = _lesen()["berichte"]
    return {"berichte": sorted(X, key=lambda b: -max([b["zeit"]] + [m["zeit"] for m in b["verlauf"]]))}


LISTE = re.compile(r"^\s*(?:[-*•]|\d+[.)]|Frage\s*\d+\s*[:.)])\s*", re.I)


def _aufteilen(text):
    """Mehrere Fragen in einer Frage (eine je Zeile, gern als Liste) werden einzelne Fragen, damit der Besitzer sie
    nacheinander bekommt. Zeilen ohne Fragezeichen gehören als Erklärung zur nächsten Frage."""
    zeilen = [LISTE.sub("", z).strip() for z in text.splitlines()]
    zeilen = [z for z in zeilen if z]
    if sum(z.endswith("?") for z in zeilen) < 2:
        return [text]
    teile, puffer = [], []
    for z in zeilen:
        puffer.append(z)
        if z.endswith("?"):
            teile.append("\n".join(puffer))
            puffer = []
    if puffer:
        teile[-1] += "\n" + "\n".join(puffer)
    return teile


def neu(von, b):
    fragen = []
    for f in (b.get("fragen") or [])[:80]:
        f = f if isinstance(f, dict) else {"text": f}
        t = _text(f.get("text"), 1000)
        vor = [_text(v, 120) for v in (f.get("vorschlaege") or [])[:6] if _text(v, 120)]
        for teil in (_aufteilen(t) if t else []):
            fragen.append({"id": hub.neue_id(fragen), "text": teil, "antwort": None, "vorschlaege": vor})
    fragen = fragen[:80]
    with _sperre:
        d = _lesen()
        if len(d["berichte"]) >= 5000:
            raise ValueError("Zu viele Berichte gespeichert.")
        x = {"id": hub.neue_id(d["berichte"]), "nr": max([b.get("nr") or 0 for b in d["berichte"]] + [0]) + 1,
             "titel": _text(b.get("titel"), 200, True), "kurz": _text(b.get("kurz"), 1000), "text": _text(b.get("text"), 200_000),
             "von": von, "sitzung": _text(b.get("sitzung"), 120), "projekt": _text(b.get("projekt"), 80), "wunsch": _text(b.get("wunsch"), 6),
             "zeit": int(time.time()), "gelesen": False, "fragen": fragen, "verlauf": []}
        d["berichte"].append(x)
        _schreiben(d)
    return x


def nachricht(von, bid, b):
    """Der Besitzer antwortet (auf eine Frage oder frei), oder der Agent des Berichts schreibt zurück."""
    with _neu:
        d = _lesen()
        x = _finden(d, bid)
        if von not in (B, x["von"]):
            raise PermissionError("Hier schreiben nur der Besitzer und der Agent, der den Bericht angelegt hat.")
        m = {"id": hub.neue_id(*[y["verlauf"] for y in d["berichte"]]), "von": von, "text": _text(b.get("text"), 8000, True), "zeit": int(time.time()), "frage": None, "abgeholt": None}
        fid = str(b.get("frage") or "")
        if fid and von == B:
            f = next((f for f in x["fragen"] if f["id"] == fid), None)
            if not f:
                raise ValueError("Diese Frage gibt es nicht.")
            f["antwort"] = {"text": m["text"], "zeit": m["zeit"]}
            m["frage"] = fid
        x["verlauf"].append(m)
        if von == B:
            x["gelesen"] = True
        _schreiben(d)
        _neu.notify_all()
    return x


def erledigt(von, bid, b):
    """Offene Fragen schließen, wenn der Besitzer sie woanders beantwortet hat (z. B. direkt im Chat mit dem Agenten).
    b: {"antworten": [Antwort je offene Frage, der Reihe nach], "notiz": „Im Chat beantwortet“}."""
    with _sperre:
        d = _lesen()
        x = _finden(d, bid)
        if von not in (B, x["von"]):
            raise PermissionError("Schließen dürfen nur der Besitzer und der Agent, der den Bericht angelegt hat.")
        notiz = _text(b.get("notiz"), 300) or "Im Chat beantwortet"
        A = [_text(a, 2000) for a in (b.get("antworten") or [])]
        jetzt, n = int(time.time()), 0
        for f in x["fragen"]:
            if not f.get("antwort"):
                f["antwort"] = {"text": (A[n] if n < len(A) and A[n] else notiz), "zeit": jetzt, "woanders": True}
                n += 1
        x["gelesen"] = True
        x["erledigt"] = jetzt
        _schreiben(d)
    return x


def gelesen(bid, ja=True):
    with _sperre:
        d = _lesen()
        x = _finden(d, bid)
        x["gelesen"] = bool(ja)
        _schreiben(d)
    return x


def _frage_text(x, m):
    f = next((f for f in x["fragen"] if f["id"] == m.get("frage")), None)
    return f"Frage {x['fragen'].index(f) + 1} von {len(x['fragen'])}: {f['text']}" if f else ""


def _offen_fuer(d, von, sitzung):
    """Nachrichten des Besitzers in Berichten dieses Agenten, die er noch nicht abgeholt hat."""
    return [(x, m) for x in d["berichte"] if x["von"] == von and not (sitzung and x["sitzung"] != sitzung)
            for m in x["verlauf"] if m["von"] == B and not m.get("abgeholt")]


def warten(von, sitzung="", sekunden=600):
    """Wartet höchstens „sekunden“, bis der Besitzer in einem Bericht dieses Agenten schreibt. Als abgeholt gelten die
    Nachrichten erst, wenn der Agent das mit abgeholt() bestätigt; so geht bei einer abgerissenen Verbindung nichts verloren."""
    try:
        sekunden = int(sekunden)
    except (TypeError, ValueError):
        sekunden = 600
    ende = time.time() + max(1, min(sekunden, 3000))
    with _neu:
        while True:
            O = _offen_fuer(_lesen(), von, sitzung)
            if O:
                return {"neu": [{"bericht": x["id"], "nr": x.get("nr"), "nachricht": m["id"], "titel": x["titel"], "frage": _frage_text(x, m),
                                 "text": m["text"], "zeit": m["zeit"], "offen": offene_fragen(x)} for x, m in O]}
            rest = ende - time.time()
            if rest <= 0:
                return {"neu": []}
            _neu.wait(min(rest, 30))


def abgeholt(von, bid, ids):
    with _sperre:
        d = _lesen()
        x = _finden(d, bid)
        if von != x["von"]:
            raise PermissionError("Nur der Agent des Berichts bestätigt Nachrichten.")
        n, jetzt = 0, int(time.time())
        for m in x["verlauf"]:
            if m["id"] in (ids or []) and m["von"] == B and not m.get("abgeholt"):
                m["abgeholt"], n = jetzt, n + 1
        if n:
            _schreiben(d)
    return {"ok": True, "bestaetigt": n}


def lesen(von, bid):
    """Ein Bericht mit Verlauf. Liest ihn sein Agent, gelten die Nachrichten des Besitzers als abgeholt."""
    with _sperre:
        d = _lesen()
        x = _finden(d, bid)
        if von == x["von"] and any(m["von"] == B and not m.get("abgeholt") for m in x["verlauf"]):
            for m in x["verlauf"]:
                if m["von"] == B and not m.get("abgeholt"):
                    m["abgeholt"] = int(time.time())
            _schreiben(d)
    return x
