#!/usr/bin/env python3
"""Claude-Code-Hook: meldet der Zentrale, wann Claude an etwas arbeitet und wann er fertig ist (Seite „Agenten“).

Eingetragen für UserPromptSubmit (Start), Stop (Fertig) und StopFailure (abgebrochen, z. B. am Limit), einrichten mit `py hooks/einrichten.py`.
Ein Lauf je Chat („chat-<session_id>“). Titel ist die erste Zeile der Nachricht des Besitzers, die Wunsch-Nummer
kommt aus „Wunsch Nr. …“ darin, aber nur beim ersten Start des Chats (spätere Nummern sind oft nur Zitate). Bei Fertig steht der Anfang von Claudes letzter Antwort als Ergebnis dabei.

Der Hook hält Claude nicht auf: Die Zentrale läuft auf diesem Rechner, gewartet wird höchstens 2 Sekunden.
Fehler (Zentrale aus, Schlüssel fehlt) werden verschluckt. Schlüssel: der von `py start.py agent-neu claude`.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def letzte_antwort(pfad):
    """Anfang der letzten Antwort von Claude aus dem Chat-Protokoll (nur das Ende der Datei lesen)."""
    try:
        with open(pfad, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 400_000))
            zeilen = f.read().decode("utf-8", "replace").splitlines()
    except (OSError, TypeError):
        return ""
    for z in reversed(zeilen):
        try:
            d = json.loads(z)
        except ValueError:
            continue
        if d.get("type") != "assistant":
            continue
        inhalt = (d.get("message") or {}).get("content") or []
        text = " ".join(c.get("text", "") for c in inhalt if isinstance(c, dict) and c.get("type") == "text").strip()
        if text:
            return " ".join(text.split())[:300]
    return ""


def main():
    try:
        h = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
    except ValueError:
        return
    ereignis, sitzung = h.get("hook_event_name"), str(h.get("session_id") or "")
    if ereignis not in ("UserPromptSubmit", "Stop", "StopFailure") or not sitzung:
        return
    lauf = "chat-" + re.sub(r"[^A-Za-z0-9._:-]", "", sitzung)[:70]
    if ereignis == "UserPromptSubmit":
        text = (h.get("prompt") or "").strip()
        erste = next((z.strip() for z in text.splitlines() if z.strip()), "")
        if erste.startswith("<"):   # Systemnachricht statt Nachricht des Besitzers: Titel des Chats bleibt
            erste, text = "", ""
        m = re.search(r"wunsch\s*(?:nr\.?|nummer)\s*(\d{1,5})", text, re.I)
        erste = re.sub(r"^\s*wunsch\s*(?:nr\.?|nummer)\s*\d{1,5}\s*[:·,.-]?\s*", "", erste, flags=re.I) or erste
        d = {"aktion": "start", "lauf": lauf, "titel": erste[:150], "wunsch": m.group(1) if m else "", "quelle": "hook", "sitzung": sitzung}
    elif ereignis == "StopFailure":
        d = {"aktion": "fertig", "lauf": lauf, "nur_wenn_aktiv": True, "quelle": "hook", "ergebnis": "Abgebrochen: " + str(h.get("last_assistant_message") or h.get("error") or "Fehler")[:200]}
    else:
        d = {"aktion": "fertig", "lauf": lauf, "nur_wenn_aktiv": True, "quelle": "hook", "ergebnis": letzte_antwort(h.get("transcript_path"))}
    try:
        from zentrale_client import Zentrale
        Zentrale(agent="claude")._anfrage("/api/laeufe", d, timeout=2)
    except Exception:
        pass


if __name__ == "__main__":
    main()
