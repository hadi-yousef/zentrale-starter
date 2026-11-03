"""Zentrale: Inventar (Seite „Inventar“): Waren, Material und Teile mit Bestand, Ort und Buchungen.

Ein Teil hat Name, Beschreibung, Kategorie, Ort, Menge, Einheit, Mindestmenge, Link und Kerndaten. Der Bestand ändert sich nur
über Buchungen (dazu oder entnommen), jede Buchung wird mit vorher und nachher gespeichert. Eingabe auch als Satz („25x Schrauben M4
dazu“, „3 Kartons entnommen“, „Wie viele Schrauben M4 habe ich?“): verstehen() macht daraus einen Vorschlag, gebucht wird erst
nach „Buchen“. Entfernt wird nichts endgültig (Markierung „entfernt“).

„zaehlung“ sagt, wie genau die Menge ist ("" gezählt, "ca" ungefähr, "offen" nicht gezählt). Unter der Mindestmenge steht ein Teil auf
der Einkaufsliste. „projekte“ nennt die Projekte, die ein Teil nutzen. Fotos: je Teil bis zu 20 JPEG oder PNG in DATEN/inventar-fotos.

Gespeichert in DATEN/inventar.json: {"teile": [...], "buchungen": [...]}. Ist die Datei unlesbar, wird nichts geschrieben.
Nach jeder Änderung schreibt die Zentrale die ganze Liste in die Notiz „Inventar/Bestand.md“, damit Agenten sie finden.
"""
import base64
import binascii
import json
import os
import re
import secrets
import threading
import time
import unicodedata

import hub
import notizen

DATEI = hub.STATE_DIR / "inventar.json"
FOTOS = hub.STATE_DIR / "inventar-fotos"
ID = re.compile(r"^[0-9a-f]{6}$")
EINHEITEN = ("Stück", "m", "kg", "l", "Karton", "Packung")
ZAEHLUNG = ("", "ca", "offen")
FOTO_MAX = 10 * 1024 * 1024
FOTO_DATEI = re.compile(r"^[0-9a-f]{6}-[0-9a-f]{6}\.(jpg|png)$")
_sperre = threading.Lock()


def _lesen():
    try:
        return json.loads(DATEI.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"teile": [], "buchungen": []}
    except (OSError, ValueError):
        raise ValueError("Das Inventar lässt sich gerade nicht lesen. Es wird nichts überschrieben.")


def _schreiben(d):
    hub.json_schreiben(DATEI, d)
    _export_spaeter()


def _text(v, n, pflicht=False):
    t = str(v or "").replace("\r\n", "\n").strip()[:n]
    if pflicht and not t:
        raise ValueError("Name fehlt")
    return t


def _zahl(v, name="Menge"):
    try:
        z = float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        raise ValueError(f"{name} ist keine Zahl.")
    if z != z or abs(z) > 1e9:
        raise ValueError(f"{name} ist ungültig.")
    return int(z) if z == int(z) else round(z, 3)


def stand():
    with _sperre:
        d = _lesen()
    T = [t for t in d["teile"] if not t.get("entfernt")]
    return {"teile": sorted(T, key=lambda t: (t["kategorie"].lower(), t["name"].lower())), "buchungen": sorted(d["buchungen"], key=lambda b: -b["zeit"])[:300]}


def _felder(t, b):
    if "name" in b:
        t["name"] = _text(b["name"], 120, True)
    for k, n in (("beschreibung", 300), ("kategorie", 60), ("ort", 120), ("link", 500), ("notiz", 2000)):
        if k in b:
            t[k] = _text(b[k], n)
    if t.get("link") and not re.match(r"^https?://", t["link"]):
        raise ValueError("Der Link muss mit http:// oder https:// anfangen.")
    if "einheit" in b:
        t["einheit"] = b["einheit"] if b["einheit"] in EINHEITEN else "Stück"
    if "min" in b:
        t["min"] = _zahl(b["min"], "Mindestmenge") if str(b["min"] if b["min"] is not None else "").strip() else None
    if "zaehlung" in b:
        if (b["zaehlung"] or "") not in ZAEHLUNG:
            raise ValueError("Zählung muss leer (gezählt), ca oder offen sein.")
        t["zaehlung"] = b["zaehlung"] or ""
    if "projekte" in b:
        L = b["projekte"] if isinstance(b["projekte"], list) else str(b["projekte"] or "").split(",")
        t["projekte"] = list(dict.fromkeys(x for x in (_text(v, 60) for v in L[:10]) if x))
    if "werte" in b:   # Kerndaten, z. B. {"Größe": "M4x20", "Lieferant": "…"}; ein leerer Wert löscht den Eintrag
        if not isinstance(b["werte"], dict):
            raise ValueError("werte: Name → Wert")
        w = dict(t.get("werte") or {})
        for k, v in list(b["werte"].items())[:30]:
            k, v = _text(k, 40), _text(v, 120)
            if k and v:
                w[k] = v
            elif k:
                w.pop(k, None)
        if len(w) > 16:
            raise ValueError("Höchstens 16 Kerndaten je Teil.")
        t["werte"] = w


def _finden(d, tid):
    t = next((x for x in d["teile"] if x["id"] == tid and not x.get("entfernt")), None) if ID.match(tid or "") else None
    if not t:
        raise ValueError("Dieses Teil gibt es nicht.")
    return t


def _anlegen(d, von, b):
    """Neues Teil in d anlegen (ohne Sperre und ohne Schreiben, das macht der Aufrufer)."""
    if len(d["teile"]) >= 20000:
        raise ValueError("Zu viele Teile.")
    jetzt = int(time.time())
    t = {"id": hub.neue_id(d["teile"]), "name": "", "beschreibung": "", "kategorie": "Unsortiert", "ort": "Noch nicht einsortiert", "menge": 0,
         "einheit": "Stück", "min": None, "zaehlung": "", "projekte": [], "link": "", "notiz": "", "von": von, "erstellt": jetzt, "geaendert": jetzt}
    _felder(t, b)
    if not t["name"]:
        raise ValueError("Name fehlt")
    t["kategorie"] = t["kategorie"] or "Unsortiert"
    t["ort"] = t["ort"] or "Noch nicht einsortiert"
    if any(x["name"].lower() == t["name"].lower() and not x.get("entfernt") for x in d["teile"]):
        raise ValueError(f"„{t['name']}“ gibt es schon. Buche stattdessen dazu.")
    d["teile"].append(t)
    return t


def teil_neu(von, b):
    with _sperre:
        d = _lesen()
        t = _anlegen(d, von, b)
        _schreiben(d)
    return t


def teil_aendern(von, tid, b):
    with _sperre:
        d = _lesen()
        t = _finden(d, tid)
        if b.get("entfernen"):
            t["entfernt"] = int(time.time())
        else:
            if "name" in b and any(x is not t and x["name"].lower() == str(b["name"]).strip().lower() and not x.get("entfernt") for x in d["teile"]):
                raise ValueError(f"„{str(b['name']).strip()}“ gibt es schon.")
            _felder(t, b)
        t["geaendert"] = int(time.time())
        _schreiben(d)
    return t


def buchen(von, b):
    """Bestand ändern. b: {teil: id} oder {neu: {name, …}}, delta (+ dazu, − entnommen), text (der Satz), quelle (satz|hand)."""
    delta = _zahl(b.get("delta"))
    if not delta:
        raise ValueError("Die Menge ist 0.")
    with _sperre:
        d = _lesen()
        t = _anlegen(d, von, b["neu"]) if isinstance(b.get("neu"), dict) else _finden(d, str(b.get("teil") or ""))
        vorher = t["menge"]
        nachher = _zahl(vorher + delta)
        if nachher < 0:
            raise ValueError(f"Es sind nur {vorher} {t['einheit']} da, so viel lässt sich nicht entnehmen.")
        t["menge"], t["geaendert"] = nachher, int(time.time())
        if b.get("zaehlung") in ZAEHLUNG:
            t["zaehlung"] = b["zaehlung"]
        x = {"id": hub.neue_id(d["buchungen"]), "teil": t["id"], "name": t["name"], "delta": delta, "vorher": vorher, "nachher": nachher, "von": von,
             "zeit": int(time.time()), "text": _text(b.get("text"), 300), "quelle": "satz" if b.get("quelle") == "satz" else "hand"}
        d["buchungen"].append(x)
        _schreiben(d)
    return {"teil": t, "buchung": x}


def foto_neu(von, tid, b):
    """Foto an ein Teil hängen. b: {bild: base64 (JPEG oder PNG), text: Beschreibung}. Gelöscht wird kein Foto."""
    try:
        roh = base64.b64decode(str(b.get("bild") or ""), validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("Das Foto ist nicht lesbar.")
    if not roh or len(roh) > FOTO_MAX:
        raise ValueError("Das Foto fehlt oder ist größer als 10 MB.")
    endung = "jpg" if roh[:3] == b"\xff\xd8\xff" else "png" if roh[:8] == b"\x89PNG\r\n\x1a\n" else ""
    if not endung:
        raise ValueError("Nur JPEG- oder PNG-Fotos.")
    with _sperre:
        d = _lesen()
        t = _finden(d, tid)
        F = t.setdefault("fotos", [])
        if len(F) >= 20:
            raise ValueError("Höchstens 20 Fotos je Teil.")
        FOTOS.mkdir(parents=True, exist_ok=True)
        name = f"{t['id']}-{secrets.token_hex(3)}.{endung}"
        tmp = FOTOS / ("." + name + ".tmp")
        tmp.write_bytes(roh)
        tmp.replace(FOTOS / name)
        F.append({"datei": name, "text": _text(b.get("text"), 200), "von": von, "zeit": int(time.time())})
        t["geaendert"] = int(time.time())
        _schreiben(d)
    return t


def foto_pfad(tid, datei):
    """Pfad eines Fotos, nur wenn es wirklich zu diesem Teil gehört."""
    with _sperre:
        t = _finden(_lesen(), tid)
    if not FOTO_DATEI.match(datei or "") or not any(f["datei"] == datei for f in t.get("fotos") or []):
        raise ValueError("Dieses Foto gibt es nicht.")
    p = FOTOS / datei
    if not p.is_file():
        raise ValueError("Das Foto liegt nicht mehr im Ordner.")
    return p


# ---------- Die ganze Liste als Notiz, zum Nachlesen für Agenten ----------

_export = {"geplant": False}


def _export_spaeter():
    if not _export["geplant"]:
        _export["geplant"] = True
        u = threading.Timer(5, _exportieren)
        u.daemon = True
        u.start()


def menge_text(t):
    e = {"Stück": "Stk.", "Karton": "Kartons", "Packung": "Pck."}.get(t.get("einheit"), t.get("einheit") or "Stk.")
    z = str(t["menge"]).replace(".", ",")
    if t.get("zaehlung") == "offen":
        return "nicht gezählt" if not t["menge"] else f"mind. {z} {e}"
    return ("ca. " if t.get("zaehlung") == "ca" else "") + f"{z} {e}"


def _zelle(v):
    return str(v or "").replace("|", "/").replace("\n", " ").strip()


def wenig(t):
    return t.get("min") is not None and t["menge"] < t["min"]


def text_liste():
    """Die Liste als Markdown."""
    with _sperre:
        d = _lesen()
    T = sorted((t for t in d["teile"] if not t.get("entfernt")), key=lambda t: (t["kategorie"].lower(), t["name"].lower()))
    luecken = [t for t in T if wenig(t)]
    z = ["# Inventar", "", f"Automatisch aus der Zentrale, Stand {time.strftime('%d.%m.%Y %H:%M')}. **Hier nichts ändern**, Änderungen gehen verloren. "
         "Ändern auf der Seite „Inventar“ oder mit `zentrale_client.py inventar-satz`.", "",
         f"{len(T)} Teile, {len(luecken)} auf der Einkaufsliste.", ""]
    for k in dict.fromkeys(t["kategorie"] for t in T):
        z += [f"## {k}", "", "| Teil | Menge | Details | Ort | Projekte |", "|---|---|---|---|---|"]
        z += [f"| {_zelle(t['name'])} | {_zelle(menge_text(t))} | {_zelle(t.get('beschreibung'))} | {_zelle(t.get('ort'))} | {_zelle(', '.join(t.get('projekte') or []))} |" for t in T if t["kategorie"] == k]
        z.append("")
    if luecken:
        z += ["## Einkaufsliste", ""] + [f"- [ ] {t['name']}" + (f" ({_zelle(t['beschreibung'])})" if t.get("beschreibung") else "") + (f", für {', '.join(t['projekte'])}" if t.get("projekte") else "") for t in luecken] + [""]
    return "\n".join(z)


def _exportieren():
    _export["geplant"] = False
    try:
        o = notizen.WURZEL / "Inventar"
        o.mkdir(parents=True, exist_ok=True)
        p = o / "Bestand.md"
        tmp = o / ".Bestand.md.tmp"
        tmp.write_bytes(text_liste().encode("utf-8"))
        os.replace(tmp, p)
    except Exception as e:   # z. B. die Notiz ist gerade in einem Editor offen: beim nächsten Mal
        print("Inventar als Notiz:", e, flush=True)


# ---------- Sätze verstehen (ohne KI) ----------

def _norm(s):
    return re.sub(r"[^a-z0-9]+", "", unicodedata.normalize("NFKD", str(s).lower()))


DAZU = r"(dazu|hinzu|bekommen|gekauft|eingelagert|rein|neu|zugang|plus)"
WEG = r"(entnommen|genommen|verbraucht|verkauft|raus|weg|verbaut|abgang|minus|entnehmen)"
EINHEIT = r"(?:x|×|stk\.?|stück|stueck|st\.?|pcs|m|meter|kg|l|liter|karton|kartons|packung|packungen|pck\.?)?"
EINHEIT_ERKENNEN = ((r"m|meter", "m"), (r"kg", "kg"), (r"l|liter", "l"), (r"karton|kartons", "Karton"), (r"packung|packungen|pck\.?", "Packung"))


def verstehen(text):
    """Macht aus einem Satz einen Vorschlag. Gebucht wird nichts."""
    s = " ".join(str(text or "").split())
    if not s:
        raise ValueError("Was soll ich eintragen?")
    with _sperre:
        T = [t for t in _lesen()["teile"] if not t.get("entfernt")]

    def treffer(name):
        n = _norm(name)
        if not n:
            return []
        gleich = [t for t in T if _norm(t["name"]) == n]
        return gleich or [t for t in T if n in _norm(t["name"]) or _norm(t["name"]) in n]

    m = re.match(r"^\s*(?:wie\s*viele?|wieviele?|wie\s*viel|haben\s*wir|habe\s*ich|bestand(?:\s*von)?)\s+(.+?)(?:\s+(?:habe ich|haben wir|sind da|da|noch))?\s*\??\s*$", s, re.I)
    if m:
        return {"art": "frage", "text": s, "suche": m.group(1), "treffer": treffer(m.group(1))}
    richtung = -1 if re.search(r"\b" + WEG + r"\b", s, re.I) else 1 if re.search(r"\b" + DAZU + r"\b", s, re.I) else 0
    rest = re.sub(r"\b(" + DAZU[1:-1] + "|" + WEG[1:-1] + r")\b", " ", s, flags=re.I).strip(" .!")
    m = re.match(r"^\s*(-?\d+(?:[.,]\d+)?)\s*(" + EINHEIT + r")\s+(.+?)\s*$", rest, re.I)
    if m:
        zahl, einh, name = m.group(1), m.group(2), m.group(3)
    else:
        m = re.match(r"^\s*(.+?)\s+(-?\d+(?:[.,]\d+)?)\s*(" + EINHEIT + r")\s*$", rest, re.I)
        if not m:
            raise ValueError("Das habe ich nicht verstanden. Beispiel: „25x Schrauben M4 dazu“ oder „3 Stück Schrauben M4 entnommen“.")
        name, zahl, einh = m.group(1), m.group(2), m.group(3)
    menge = _zahl(zahl)
    if menge < 0:
        richtung, menge = -1, -menge
    if not menge:
        raise ValueError("Die Menge ist 0.")
    einheit = next((e for muster, e in EINHEIT_ERKENNEN if re.fullmatch(muster, einh or "", re.I)), "Stück")
    name = re.sub(r"^(stück|stk\.?|x|von|vom|der|die|das)\s+", "", name.strip(), flags=re.I)
    L = treffer(name)
    return {"art": "buchung", "text": s, "richtung": richtung or 1, "richtung_sicher": bool(richtung), "menge": menge, "einheit": einheit, "name": name, "treffer": L, "neu": not L}
