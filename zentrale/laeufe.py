"""Zentrale: Läufe (Seite „Agenten“). Wer arbeitet gerade woran, was ist fertig.

Ein Lauf ist eine Arbeit eines Agenten: Start, Zwischenstand, Fertig. Der Agent kommt immer aus dem Schlüssel,
nie aus dem Inhalt der Anfrage. Gemeldet wird vom Claude-Code-Hook (`hooks/claude_lauf.py`, von selbst) und von Hand
(`zentrale_client.py lauf start|stand|fertig`, so meldet sich Codex).

Gespeichert in DATEN/laeufe.json: {"aktiv": {"agent|lauf": Lauf}, "fertig": [Lauf, …]} (älteste zuerst)
  Lauf = {agent, lauf, start, t (letztes Lebenszeichen), titel, schritt, wunsch (Nr.), fortschritt (0–100 oder None),
          quelle, sitzung, beim Ende: ende, status (fertig|fehler|abgebrochen), ergebnis}
"""
import re
import threading
import time

import hub

DATEI = hub.STATE_DIR / "laeufe.json"
FERTIG_MAX = 300        # so viele fertige Läufe bleiben gespeichert
STILL_S = 1800          # ohne Lebenszeichen so lange gilt ein Lauf als „still“ (grau statt grün)
WEG_S = 6 * 3600        # ohne Lebenszeichen so lange, dann wird er als abgebrochen abgelegt
KURZ_S = 20             # Hook-Läufe, die kürzer sind (kurze Chat-Antworten), werden nicht als fertig abgelegt
LAUF_ID = re.compile(r"^[A-Za-z0-9._:-]{1,80}$")

_lock = threading.Lock()
_d = hub._json_laden(DATEI, {})
_aktiv = dict(_d.get("aktiv") or {})
_fertig = list(_d.get("fertig") or [])[-FERTIG_MAX:]


def _sichern():
    """Aufrufen, während _lock gehalten wird."""
    try:
        hub.json_schreiben(DATEI, {"aktiv": _aktiv, "fertig": _fertig})
    except OSError:
        pass


def _txt(v, n):
    return re.sub(r"\s+", " ", str(v)).strip()[:n] if v not in (None, "") else ""


def wunsch_nr(v):
    """7, "7", "Nr. 7" oder ein Text mit „Wunsch Nr. 7“ → 7, sonst None."""
    if isinstance(v, int) and not isinstance(v, bool):
        return v if 0 < v < 100000 else None
    s = str(v or "")
    m = re.fullmatch(r"\s*(?:nr\.?\s*)?(\d{1,5})\s*", s, re.I) or re.search(r"wunsch\s*(?:nr\.?|nummer)\s*(\d{1,5})", s, re.I)
    return int(m.group(1)) if m and int(m.group(1)) > 0 else None


def melden(aid, d):
    """Start, Zwischenstand oder Fertig eines Laufs. Antwort: der Lauf ({} bei nur_wenn_aktiv ohne laufenden Lauf)."""
    aktion = d.get("aktion")
    if aktion not in ("start", "stand", "fertig"):
        raise ValueError("aktion muss start, stand oder fertig sein")
    lauf = str(d.get("lauf") or "haupt")
    if not LAUF_ID.match(lauf):
        raise ValueError("lauf: nur Buchstaben, Ziffern und ._:- (bis 80 Zeichen)")
    jetzt = time.time()
    felder = {"titel": _txt(d.get("titel"), 160), "schritt": _txt(d.get("schritt"), 200),
              "quelle": _txt(d.get("quelle"), 20), "sitzung": _txt(d.get("sitzung"), 80)}
    w = wunsch_nr(d.get("wunsch")) or wunsch_nr(felder["titel"])
    fp = d.get("fortschritt")
    fp = max(0, min(100, fp)) if isinstance(fp, (int, float)) and not isinstance(fp, bool) else None
    k = f"{aid}|{lauf}"
    with _lock:
        alt = _aktiv.get(k)
        if aktion == "fertig" and not alt and d.get("nur_wenn_aktiv"):
            return {}
        if aktion == "start" and (not w or not felder["titel"] or felder["quelle"] == "hook"):   # Folge-Nachricht im selben Chat: Wunsch und Titel behalten
            vorher = alt or next((x for x in reversed(_fertig) if x["agent"] == aid and x["lauf"] == lauf), None) or {}
            # Der Hook nimmt die Nummer nur beim ersten Start: Eine zitierte Nummer verschiebt den laufenden Chat nicht
            w = (vorher.get("wunsch") or w) if felder["quelle"] == "hook" else (w or vorher.get("wunsch"))
            felder["titel"] = felder["titel"] or vorher.get("titel", "")
        if aktion == "start" or not alt:
            if alt and aktion == "start" and jetzt - alt["start"] >= 60:   # nie fertig gemeldet: als abgebrochen ablegen
                _fertig.append(dict(alt, ende=alt.get("t") or jetzt, status="abgebrochen"))
            alt = {"agent": aid, "lauf": lauf, "start": jetzt, "titel": "", "schritt": "", "quelle": "", "sitzung": "",
                   "wunsch": None, "fortschritt": None}
        x = dict(alt, t=jetzt)
        for f, v in felder.items():
            if v:
                x[f] = v
        if w:
            x["wunsch"] = w
        if fp is not None:
            x["fortschritt"] = fp
        if aktion == "fertig":
            _aktiv.pop(k, None)
            x.update(ende=jetzt, status="fehler" if d.get("fehler") else "fertig", ergebnis=_txt(d.get("ergebnis"), 600))
            if x["quelle"] != "hook" or jetzt - x["start"] >= KURZ_S:
                _fertig.append(x)
            del _fertig[:-FERTIG_MAX]
        else:
            _aktiv[k] = x
        _sichern()
    return x


def lage(n=60):
    """Für die Oberfläche: aktive Läufe (älteste zuerst) und die letzten fertigen (neueste zuerst)."""
    jetzt = time.time()
    with _lock:
        weg = [k for k, x in _aktiv.items() if jetzt - x.get("t", x["start"]) > WEG_S]
        for k in weg:
            x = _aktiv.pop(k)
            _fertig.append(dict(x, ende=x.get("t") or jetzt, status="abgebrochen"))
        if weg:
            del _fertig[:-FERTIG_MAX]
            _sichern()
        aktiv = [dict(x, still=jetzt - x.get("t", x["start"]) > STILL_S) for x in _aktiv.values()]
        fertig = list(reversed(_fertig[-n:]))
    aktiv.sort(key=lambda x: x["start"])
    return {"aktiv": aktiv, "fertig": fertig, "jetzt": jetzt}
