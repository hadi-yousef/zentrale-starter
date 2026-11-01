"""Zentrale: Schlüssel und Agenten.

Jeder Agent (Claude Code, Codex, ein Skript) hat einen eigenen Schlüssel. Die Agenten-ID kommt immer aus dem Schlüssel,
nie aus dem Inhalt einer Anfrage, damit sich kein Agent als ein anderer ausgeben kann. Der Eintrag „besitzer“ ist der
Schlüssel für die Bedienung in der Oberfläche.

Gespeichert wird nur eine Prüfsumme (SHA-256) je Schlüssel, nie der Schlüssel selbst:
  DATEN/schluessel.json = {"besitzer": {"hash": "…", "erstellt": 1700000000}, "claude": {…}}
Wann ein Agent zuletzt etwas wollte, steht in DATEN/agenten.json.
"""
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from pathlib import Path

STATE_DIR = Path(os.environ.get("ZENTRALE_DATEN") or Path(__file__).resolve().parent.parent / "daten")
SCHLUESSEL = STATE_DIR / "schluessel.json"
BESITZER = "besitzer"
MAX_BODY = 64 * 1024
FASSUNG = "2026-11-05"   # bei jedem Update hochsetzen, auch FASSUNG in index.src.html; der Client und die Seite vergleichen
ORDNER = Path(__file__).resolve().parent.parent   # der Ordner dieser Zentrale (zentrale-starter)
ORDNER_ID = hashlib.sha256(str(ORDNER).lower().encode("utf-8")).hexdigest()[:12]   # Kennung ohne Pfad, für /api/lebt
HEIMNETZ = False   # setzt start.py: hört die Zentrale auch auf andere Geräte (Tailscale)?
LAN_OFFEN = False  # setzt start.py mit --lan-unverschluesselt: auch das normale Heimnetz, unverschlüsselt
ABGEWIESEN = {}    # Adresse aus dem Heimnetz -> Zeit der letzten abgewiesenen Anfrage (Hinweis auf der Seite „Geräte“)
PORT = 8090

_lock = threading.Lock()
_cache = {"mtime": None, "map": {}}
_gesehen = {}
_gespeichert = 0.0


def _json_laden(p, sonst):
    """JSON lesen. Fehlt die Datei: sonst. Ist sie kaputt, wird sie beiseitegelegt (nicht beim nächsten Speichern
    überschrieben) und es geht mit sonst weiter."""
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return sonst
    except (OSError, ValueError) as e:
        try:
            p.rename(p.with_name(f"{p.name}.kaputt-{int(time.time())}"))
        except OSError:
            pass
        print(f"{p.name} unlesbar, beiseitegelegt: {e}", flush=True)
        return sonst


def json_schreiben(p, d):
    """Erst in eine Zwischendatei schreiben, dann ersetzen: so ist die Datei nie halb geschrieben."""
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_bytes(json.dumps(d, ensure_ascii=False).encode("utf-8"))
    tmp.replace(p)


def _pruefsumme(schluessel):
    return hashlib.sha256(schluessel.encode()).hexdigest()


# Unter Windows darf keine Datei so heißen (auch nicht mit Endung), deshalb auch kein Agent
WINDOWS_RESERVIERT = {"con", "prn", "aux", "nul"} | {f"com{i}" for i in range(10)} | {f"lpt{i}" for i in range(10)}


def gueltige_id(aid):
    return (bool(aid) and len(aid) <= 40 and aid.isascii() and all(c.isalnum() or c in "-_" for c in aid)
            and aid.lower() not in WINDOWS_RESERVIERT)


def schluessel_neu(aid):
    """Neuen Schlüssel für einen Agenten (oder den Besitzer) erzeugen. Gibt den Schlüssel zurück; gespeichert wird nur
    seine Prüfsumme. Ein alter Schlüssel derselben ID gilt danach nicht mehr."""
    if not gueltige_id(aid):
        raise ValueError("Name bitte nur aus Buchstaben, Ziffern, - und _ (höchstens 40 Zeichen).")
    s = secrets.token_urlsafe(24)
    with _lock:
        d = _json_laden(SCHLUESSEL, {})
        d[aid] = {"hash": _pruefsumme(s), "erstellt": int(time.time())}
        json_schreiben(SCHLUESSEL, d)
        try:
            os.chmod(SCHLUESSEL, 0o600)   # Mac und Linux: nur für dich lesbar. Unter Windows schützt das Benutzerprofil.
        except OSError:
            pass
    return s


def schluessel_weg(aid):
    with _lock:
        d = _json_laden(SCHLUESSEL, {})
        if aid not in d:
            raise ValueError("Diesen Agenten gibt es nicht.")
        del d[aid]
        json_schreiben(SCHLUESSEL, d)


def ids():
    return sorted(_json_laden(SCHLUESSEL, {}))


def hat_besitzer():
    return BESITZER in _json_laden(SCHLUESSEL, {})


def who(auth_header):
    """Liefert die Agenten-ID zum Bearer-Schlüssel oder None."""
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    given = _pruefsumme(auth_header[7:].strip())
    try:
        m = SCHLUESSEL.stat().st_mtime_ns
        if m != _cache["mtime"]:
            d = _json_laden(SCHLUESSEL, {})
            _cache.update(mtime=m, map={v.get("hash"): k for k, v in d.items() if isinstance(v, dict)})
    except OSError:
        return None
    for h, aid in _cache["map"].items():
        if h and hmac.compare_digest(h, given):
            _gesehen_setzen(aid)
            return aid
    return None


def _gesehen_setzen(aid):
    global _gespeichert
    with _lock:
        _gesehen[aid] = int(time.time())
        if time.time() - _gespeichert > 30:
            _gespeichert = time.time()
            try:
                json_schreiben(STATE_DIR / "agenten.json", _gesehen)
            except OSError:
                pass


def agenten():
    """Alle Schlüssel mit ihrem letzten Kontakt (für die Übersicht)."""
    d = _json_laden(SCHLUESSEL, {})
    with _lock:
        g = dict(_gesehen)
    # Geräte-Schlüssel (geraet-…) sind keine Agenten; sie stehen unter Homelab → Geräte
    return {"agenten": [{"id": k, "erstellt": v.get("erstellt"), "zuletzt": g.get(k)} for k, v in sorted(d.items()) if not k.startswith("geraet-")]}


_gesehen.update(_json_laden(STATE_DIR / "agenten.json", {}))


def neue_id(*listen):
    """Kurze Kennung (6 Hex-Zeichen), die es in den übergebenen Listen noch nicht gibt (Prüfung 31.10.2026, R-01):
    16,7 Mio. Möglichkeiten reichen nur mit dieser Prüfung, ohne sie stoßen bei einigen tausend Einträgen zwei zusammen.
    Aufrufen, während die Sperre des Moduls gehalten wird."""
    vorhanden = {x.get("id") for l in listen for x in (l or []) if isinstance(x, dict)}
    while True:
        i = secrets.token_hex(3)
        if i not in vorhanden:
            return i
