"""Zentrale: Inventar (Seite „Inventar“): Waren, Material und Teile mit Bestand, Ort und Buchungen.

Ein Teil hat Name, Beschreibung, Kategorie, Ort, Menge, Einheit, Mindestmenge, Link und Kerndaten. Der Bestand ändert sich nur
über Buchungen (dazu oder entnommen), jede Buchung wird mit vorher und nachher gespeichert. Eingabe auch als Satz („25x Schrauben M4
dazu“, „3 Kartons entnommen“, „Wie viele Schrauben M4 habe ich?“): verstehen() macht daraus einen Vorschlag, gebucht wird erst
nach „Buchen“. Entfernt wird nichts endgültig (Markierung „entfernt“).

„zaehlung“ sagt, wie genau die Menge ist ("" gezählt, "ca" ungefähr, "offen" nicht gezählt). Unter der Mindestmenge steht ein Teil auf
der Einkaufsliste. „projekte“ nennt die Projekte, die ein Teil nutzen. Fotos: je Teil bis zu 20 JPEG oder PNG in DATEN/inventar-fotos.

Standorte (Läden, Lager …, angelegt über standort()): Gibt es welche, hat ein Teil „mengen“ je Standort, und „menge“ ist die Summe der
Standorte, die zum Bestand zählen (ein Standort mit verkaufbar: false, etwa „Beschädigt“, zählt nicht mit). Zählen (zaehlen()) nimmt die
gezählte Zahl, die Zentrale rechnet den Unterschied und bucht ihn; „gezaehlt“ hält je Standort den Zeitpunkt der letzten Zählung
(fehlt = dort nie gezählt, angezeigt als „–“, nicht als 0). „ort“ bleibt der Lagerplatz (z. B. „Regal 2“).
Ein Teil von vor den Standorten (ohne „mengen“) mit Bestand wird zuerst gezählt: Die erste Zählung an einem Standort, der zum Bestand
zählt, nimmt den bisherigen Bestand als „vorher“. So geht nichts verloren und der Verlauf bleibt lückenlos. Bis jeder Standort, der zum
Bestand zählt, einmal gezählt ist, steht „zaehlung_offen“ am Teil: Die Menge ist dann vorläufig zu klein, das Teil kommt deshalb nicht auf
die Einkaufsliste (Befund der Prüfung vom 5.11.2026).
„artnr“: Artikelnummer, eindeutig wie der Name; überall, wo ein Teil gemeint ist, geht statt der Kennung auch sie.
Vorlagen (vorlage()): je Kategorie eine geordnete Liste von Merkmalen, wahlweise mit Standardwert für neue Teile; die Werte stehen in
„werte“ (bis 60 je Teil). „vergleich“: alte Stände und andere Zahlen nur zum Ansehen, nie in „menge“ gerechnet.

Gespeichert in DATEN/inventar.json: {"teile": [...], "buchungen": [...], "standorte": [...], "vorlagen": {...}}. Ist die Datei unlesbar,
wird nichts geschrieben. Nach jeder Änderung schreibt die Zentrale die ganze Liste in die Notiz „Inventar/Bestand.md“, damit Agenten sie
finden.
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
ARTNR = re.compile(r"^(?!\.+$)[\w.+-]{1,40}$")   # nur Punkte nicht: „..“ wäre im Pfad ein Ordner höher
EINHEITEN = ("Stück", "m", "kg", "l", "Karton", "Packung")
ZAEHLUNG = ("", "ca", "offen")
FOTO_MAX = 10 * 1024 * 1024
FOTO_DATEI = re.compile(r"^[0-9a-f]{6}-[0-9a-f]{6}\.(jpg|png)$")
WERTE_MAX = 60
VERGLEICH_MAX = 20
STANDORTE_MAX = 12
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


def _standorte(d):
    return d.get("standorte") or []


def _ort(d, name):
    """Den Standort so geschrieben, wie er angelegt ist (groß/klein egal), sonst Fehler mit den bekannten Standorten."""
    n = str(name or "").strip()
    s = next((s for s in _standorte(d) if s["name"].lower() == n.lower()), None)
    if not s:
        bekannt = ", ".join(s["name"] for s in _standorte(d)) or "noch keine"
        raise ValueError(f"Den Standort „{n}“ gibt es nicht (angelegt: {bekannt}).")
    return s


def _summe(d, t):
    """Bestand eines Teils mit „mengen“: Summe der Standorte, die zum Bestand zählen."""
    zaehlt = {s["name"] for s in _standorte(d) if s.get("verkaufbar", True)}
    return _zahl(sum(m for o, m in (t.get("mengen") or {}).items() if o in zaehlt))


def stand():
    with _sperre:
        d = _lesen()
    T = [t for t in d["teile"] if not t.get("entfernt")]
    return {"teile": sorted(T, key=lambda t: (t["kategorie"].lower(), t["name"].lower())), "buchungen": sorted(d["buchungen"], key=lambda b: -b["zeit"])[:300],
            "standorte": _standorte(d), "vorlagen": d.get("vorlagen") or {}}


def _paare(alt, neu, n_max, name):
    """Name → Wert zusammenführen (werte, vergleich); ein leerer Wert löscht den Eintrag. Groß/klein egal: „typ“ und „Typ“ sind
    derselbe Eintrag (der vorhandene Name bleibt). Geprüft wird die Anzahl erst am Ende, damit Löschen und Neues im selben Schritt geht."""
    if not isinstance(neu, dict):
        raise ValueError(f"{name}: Name → Wert")
    if len(neu) > 1000:
        raise ValueError(f"Zu viele {name} auf einmal.")
    w = dict(alt or {})
    for k, v in neu.items():
        k, v = _text(k, 40), _text(v, 120)
        if not k:
            continue
        k = next((x for x in w if x.lower() == k.lower()), k)
        if v:
            w[k] = v
        else:
            w.pop(k, None)
    if len(w) > n_max:
        raise ValueError(f"Höchstens {n_max} {name} je Teil.")
    return w


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
    if "werte" in b:   # Kerndaten bzw. Merkmale, z. B. {"Größe": "M4x20", "Lieferant": "…"}
        t["werte"] = _paare(t.get("werte"), b["werte"], WERTE_MAX, "Merkmale")
    if "vergleich" in b:   # nur zum Ansehen, z. B. {"Zählung 19.10.": "79"}
        t["vergleich"] = _paare(t.get("vergleich"), b["vergleich"], VERGLEICH_MAX, "Vergleichswerte")
    if "artnr" in b:
        a = _text(b["artnr"], 41)
        if a and not ARTNR.match(a):
            raise ValueError("Die Artikelnummer darf bis zu 40 Buchstaben, Ziffern und . + - _ haben (ohne Leerzeichen).")
        if a and ID.match(a.lower()):
            raise ValueError("Sechs Zeichen nur aus 0–9 und a–f sehen aus wie eine Kennung der Zentrale. Bitte anders, zum Beispiel A-" + a + ".")
        t["artnr"] = a


def _eindeutig(d, t, selbst=None):
    """Name und Artikelnummer gibt es nur einmal (groß/klein egal). selbst: das Teil, das gerade geändert wird."""
    for x in d["teile"]:
        if x is t or x is selbst or x.get("entfernt"):
            continue
        if x["name"].lower() == t["name"].lower():
            raise ValueError(f"„{t['name']}“ gibt es schon.")
        if t.get("artnr") and (x.get("artnr") or "").lower() == t["artnr"].lower():
            raise ValueError(f"Die Artikelnummer {t['artnr']} hat schon „{x['name']}“.")


def _finden(d, tid):
    """Teil über die Kennung oder die Artikelnummer."""
    tid = str(tid or "").strip()
    L = [x for x in d["teile"] if not x.get("entfernt")]
    t = next((x for x in L if x["id"] == tid), None) if ID.match(tid) else None
    if not t and tid:
        t = next((x for x in L if (x.get("artnr") or "").lower() == tid.lower()), None)
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
    try:
        _eindeutig(d, t)
    except ValueError as e:
        raise ValueError(str(e) + (" Buche stattdessen dazu." if "gibt es schon" in str(e) else ""))
    vorlage = next((v for k, v in (d.get("vorlagen") or {}).items() if k.lower() == t["kategorie"].lower()), [])
    for m in vorlage:   # Standardwerte der Vorlage, wenn der Wert nicht mitkam
        if m.get("standard") and not any(k.lower() == m["name"].lower() for k in t.get("werte") or {}):
            t.setdefault("werte", {})[m["name"]] = m["standard"]
    if _standorte(d):
        t["mengen"], t["gezaehlt"] = {}, {}
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
            probe = dict(t)   # erst prüfen, dann übernehmen: ein Fehler ändert nichts
            _felder(probe, b)
            _eindeutig(d, probe, selbst=t)
            t.update(probe)
        t["geaendert"] = int(time.time())
        _schreiben(d)
    return t


def _ohne_standorte(d, t):
    """Gibt es keine Standorte (mehr), hat kein Teil „mengen“: dann ist „menge“ allein der Bestand. Fängt alte Daten ab, siehe standort()."""
    if not _standorte(d):
        t.pop("mengen", None)
        t.pop("gezaehlt", None)
        t.pop("zaehlung_offen", None)


def _buchung(d, t, von, delta, standort, text, quelle):
    """Eine Buchung an t (mit Standort: nur dort). Gibt die Buchung zurück; prüft, dass nirgends weniger als 0 bleibt."""
    jetzt = int(time.time())
    x = {"id": hub.neue_id(d["buchungen"]), "teil": t["id"], "name": t["name"], "delta": delta, "von": von, "zeit": jetzt,
         "text": _text(text, 300), "quelle": quelle}
    if str(standort or "").strip():
        s = _ort(d, standort)
        if "mengen" not in t:
            if t["menge"]:
                raise ValueError(f"„{t['name']}“ hat noch {t['menge']} {t['einheit']} ohne Standort. Erst an einem Standort zählen, "
                                 "danach geht das Buchen je Standort.")
            t["mengen"], t["gezaehlt"] = {}, t.get("gezaehlt") or {}
        vorher = t["mengen"].get(s["name"], 0)
        nachher = _zahl(vorher + delta)
        if nachher < 0:
            raise ValueError(f"Am Standort {s['name']} sind nur {vorher} {t['einheit']} da, so viel lässt sich nicht entnehmen.")
        t["mengen"][s["name"]] = nachher
        t["menge"] = _summe(d, t)
        x["standort"] = s["name"]
    else:
        if t.get("mengen") is not None and _standorte(d):
            raise ValueError("An welchem Standort? " + ", ".join(s["name"] for s in _standorte(d)) + ".")
        _ohne_standorte(d, t)
        vorher = t["menge"]
        nachher = _zahl(vorher + delta)
        if nachher < 0:
            raise ValueError(f"Es sind nur {vorher} {t['einheit']} da, so viel lässt sich nicht entnehmen.")
        t["menge"] = nachher
    x["vorher"], x["nachher"] = vorher, nachher
    t["geaendert"] = jetzt
    d["buchungen"].append(x)
    return x


def buchen(von, b):
    """Bestand ändern. b: {teil: id oder Artikelnummer} oder {neu: {name, …}}, delta (+ dazu, − entnommen), standort (wenn es Standorte
    gibt), text (der Satz), quelle (satz|hand). Mit Standort sind vorher und nachher die Menge an diesem Standort."""
    delta = _zahl(b.get("delta"))
    if not delta:
        raise ValueError("Die Menge ist 0.")
    with _sperre:
        d = _lesen()
        t = _anlegen(d, von, b["neu"]) if isinstance(b.get("neu"), dict) else _finden(d, str(b.get("teil") or ""))
        x = _buchung(d, t, von, delta, b.get("standort"), b.get("text"), "satz" if b.get("quelle") == "satz" else "hand")
        if b.get("zaehlung") in ZAEHLUNG:
            t["zaehlung"] = b["zaehlung"]
        _schreiben(d)
    return {"teil": t, "buchung": x}


def zaehlen(von, b):
    """Gezählt: b {teil (Kennung oder Artikelnummer), standort (wenn es Standorte gibt), menge (die gezählte Zahl), text}. Die Zentrale
    bucht den Unterschied (quelle „zaehlung“) und merkt sich den Zeitpunkt; gleiche Zahl wie vorher: keine Buchung, nur der Zeitpunkt."""
    menge = _zahl(b.get("menge"))
    if menge < 0:
        raise ValueError("Eine gezählte Menge ist nie kleiner als 0.")
    with _sperre:
        d = _lesen()
        t = _finden(d, str(b.get("teil") or ""))
        jetzt = int(time.time())
        text = _text(b.get("text"), 300)
        st = str(b.get("standort") or "").strip()
        if _standorte(d) and not st:
            raise ValueError("An welchem Standort? " + ", ".join(s["name"] for s in _standorte(d)) + ".")
        if st:   # ohne angelegte Standorte lehnt _ort ab, statt den Standort still zu übergehen
            s = _ort(d, st)
            if "mengen" not in t:   # Teil von vor den Standorten: sein Bestand gilt als hier gezählt (siehe Kopf)
                if t["menge"] and not s.get("verkaufbar", True):
                    raise ValueError(f"„{t['name']}“ hat noch {t['menge']} {t['einheit']} ohne Standort. Zuerst an einem Standort zählen, "
                                     "der zum Bestand zählt.")
                vorher = t["menge"]
                t["mengen"], t["gezaehlt"] = {}, {}
                if t["menge"]:
                    t["zaehlung_offen"] = True
                text = text or "Erste Zählung je Standort, vorher ohne Standort"
            else:
                vorher = t["mengen"].get(s["name"], 0)
            t["mengen"][s["name"]] = menge
            t.setdefault("gezaehlt", {})[s["name"]] = jetzt
            if t.get("zaehlung_offen") and all(x["name"] in t["gezaehlt"] for x in _standorte(d) if x.get("verkaufbar", True)):
                t.pop("zaehlung_offen")
            t["menge"] = _summe(d, t)
            if s.get("verkaufbar", True):   # gezählt ist gezählt: kein „mind.“ oder „nicht gezählt“ mehr
                t["zaehlung"] = ""
            ort = s["name"]
        else:
            _ohne_standorte(d, t)
            vorher, ort = t["menge"], None
            t["menge"], t["zaehlung"] = menge, ""
        delta = _zahl(menge - vorher)
        x = None
        if delta:
            x = {"id": hub.neue_id(d["buchungen"]), "teil": t["id"], "name": t["name"], "delta": delta, "vorher": vorher, "nachher": menge,
                 "von": von, "zeit": jetzt, "text": text or f"Gezählt: {str(menge).replace('.', ',')}", "quelle": "zaehlung"}
            if ort:
                x["standort"] = ort
            d["buchungen"].append(x)
        t["geaendert"] = jetzt
        _schreiben(d)
    return {"teil": t, "buchung": x}


def standort_da(name):
    """Gibt es den Standort schon (Groß und klein egal)?"""
    n = str(name or "").strip().lower()
    with _sperre:
        return any(s["name"].lower() == n for s in _standorte(_lesen()))


def standort(von, b):
    """Standort anlegen oder ändern: b {name, adresse, verkaufbar (Standard ja), entfernen}. Umbenennen geht nicht. Ob ein Standort zum
    Bestand zählt, ändert sich und entfernt wird er nur, solange dort nichts liegt."""
    name = _text(b.get("name"), 41, True)
    if len(name) > 40 or "\n" in name:
        raise ValueError("Der Name eines Standorts hat höchstens 40 Zeichen in einer Zeile.")
    with _sperre:
        d = _lesen()
        S = d.setdefault("standorte", [])
        s = next((x for x in S if x["name"].lower() == name.lower()), None)
        belegt = bool(s) and any((t.get("mengen") or {}).get(s["name"]) for t in d["teile"] if not t.get("entfernt"))
        if b.get("entfernen"):
            if not s:
                raise ValueError(f"Den Standort „{name}“ gibt es nicht.")
            if belegt:
                raise ValueError(f"Am Standort {s['name']} liegt noch etwas. Erst dort auf 0 zählen, dann entfernen.")
            S.remove(s)
            for t in d["teile"]:   # seine Zahlen vergessen (sonst zeigt ein neuer Standort gleichen Namens „0“ statt „–“)
                (t.get("mengen") or {}).pop(s["name"], None)
                (t.get("gezaehlt") or {}).pop(s["name"], None)
                if not S:   # kein Standort mehr: zurück zu einer Menge je Teil, verlustfrei, weil jeder Standort leer war
                    t.pop("mengen", None)
                    t.pop("gezaehlt", None)
        else:
            if not s:
                if len(S) >= STANDORTE_MAX:
                    raise ValueError(f"Höchstens {STANDORTE_MAX} Standorte.")
                s = {"name": name, "adresse": "", "verkaufbar": True}
                S.append(s)
                for t in d["teile"]:   # Teile mit Bestand ohne Standort bleiben, wie sie sind, bis sie gezählt werden
                    if not t.get("entfernt") and "mengen" not in t and not t["menge"]:
                        t["mengen"], t["gezaehlt"] = {}, {}
            if "adresse" in b:
                s["adresse"] = _text(b["adresse"], 120)
            if "verkaufbar" in b and bool(b["verkaufbar"]) != s.get("verkaufbar", True):
                if belegt:
                    raise ValueError(f"Am Standort {s['name']} liegt noch etwas. Ob er zum Bestand zählt, ändert sich nur, solange er leer ist.")
                s["verkaufbar"] = bool(b["verkaufbar"])
        _schreiben(d)
    return {"standorte": S}


def vorlage(von, b):
    """Merkmale je Kategorie: b {kategorie, merkmale: [{name, standard}] oder ["Typ", "Hersteller=Muster"]}. Setzt die ganze Liste, die
    Reihenfolge ist die der Anzeige. Ein Merkmal fällt nur weg, wenn kein Teil der Kategorie einen Wert dafür hat."""
    kat = _text(b.get("kategorie"), 60)
    if not kat:
        raise ValueError("Kategorie fehlt.")
    L = b.get("merkmale")
    if not isinstance(L, list):
        raise ValueError("merkmale: eine Liste")
    neu = []
    for m in L[:WERTE_MAX + 1]:
        n, s = (m.get("name"), m.get("standard")) if isinstance(m, dict) else str(m).partition("=")[::2]
        n, s = _text(n, 40), _text(s, 120)
        if not n:
            continue
        if any(x["name"].lower() == n.lower() for x in neu):
            raise ValueError(f"„{n}“ steht zweimal in der Vorlage.")
        neu.append({"name": n, **({"standard": s} if s else {})})
    if len(neu) > WERTE_MAX:
        raise ValueError(f"Höchstens {WERTE_MAX} Merkmale je Vorlage.")
    with _sperre:
        d = _lesen()
        V = d.setdefault("vorlagen", {})
        schluessel = next((k for k in V if k.lower() == kat.lower()), kat)
        bleibt = {x["name"].lower() for x in neu}
        for m in V.get(schluessel) or []:
            if m["name"].lower() in bleibt:
                continue
            mit = next((t for t in d["teile"] if not t.get("entfernt") and t["kategorie"].lower() == kat.lower()
                        and any(k.lower() == m["name"].lower() for k in t.get("werte") or {})), None)
            if mit:
                raise ValueError(f"„{m['name']}“ hat bei „{mit['name']}“ noch einen Wert. Erst dort leeren, dann aus der Vorlage nehmen.")
        if neu:
            V[schluessel] = neu
        else:
            V.pop(schluessel, None)
        _schreiben(d)
    return {"vorlagen": V}


IMPORT_FELDER = ("name", "artnr", "beschreibung", "kategorie", "ort", "einheit", "min", "zaehlung", "projekte", "link", "notiz", "werte", "vergleich")


def teile_import(von, b):
    """Viele Teile auf einmal: b {teile: [{name, artnr, kategorie, werte, vergleich, …}], probe}. Ganz oder gar nicht: Alles wird an einer
    Kopie mit denselben Regeln wie beim einzelnen Anlegen geprüft; mit probe (oder bei einem Fehler) wird nichts geschrieben."""
    L = b.get("teile")
    if not isinstance(L, list) or not L:
        raise ValueError("teile: eine Liste mit mindestens einem Teil")
    if len(L) > 2000:
        raise ValueError("Höchstens 2000 Teile auf einmal.")
    with _sperre:
        d = _lesen()
        kopie = json.loads(json.dumps(d))
        neu, fehler = [], []
        for i, x in enumerate(L, 1):
            try:
                if not isinstance(x, dict):
                    raise ValueError("kein Teil (Name → Wert)")
                fremd = sorted(set(x) - set(IMPORT_FELDER))
                if fremd:
                    raise ValueError("unbekannte Felder " + ", ".join(fremd))
                neu.append(_anlegen(kopie, von, x))
            except (ValueError, TypeError) as e:
                fehler.append(f"Nr. {i}" + (f" („{str(x.get('name') or '')[:60]}“)" if isinstance(x, dict) else "") + f": {e}")
        if fehler:
            raise ValueError(f"Nichts angelegt, {len(fehler)} {'Problem' if len(fehler) == 1 else 'Probleme'}: " + " · ".join(fehler[:20])
                             + (" · …" if len(fehler) > 20 else ""))
        if not b.get("probe"):
            _schreiben(kopie)
    return {"teile": neu, "probe": bool(b.get("probe"))}


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


def orte_text(standorte, t):
    """„Laden – · Lager 47 · Beschädigt 2“: je Standort die Menge, „–“ = dort nie gezählt und nichts gebucht."""
    if t.get("mengen") is None or not standorte:
        return ""
    M, G = t.get("mengen") or {}, t.get("gezaehlt") or {}
    return " · ".join(f"{s['name']} " + (str(M.get(s["name"], 0)).replace(".", ",") if s["name"] in M or s["name"] in G else "–")
                      for s in standorte)


def _zelle(v):
    return str(v or "").replace("|", "/").replace("\n", " ").strip()


def wenig(t):
    return t.get("min") is not None and t["menge"] < t["min"] and not t.get("zaehlung_offen")


def text_liste():
    """Die Liste als Markdown."""
    with _sperre:
        d = _lesen()
    S = _standorte(d)
    T = sorted((t for t in d["teile"] if not t.get("entfernt")), key=lambda t: (t["kategorie"].lower(), t["name"].lower()))
    luecken = [t for t in T if wenig(t)]
    z = ["# Inventar", "", f"Automatisch aus der Zentrale, Stand {time.strftime('%d.%m.%Y %H:%M')}. **Hier nichts ändern**, Änderungen gehen verloren. "
         "Ändern auf der Seite „Inventar“ oder mit `zentrale_client.py inventar-satz`.", "",
         f"{len(T)} Teile, {len(luecken)} auf der Einkaufsliste.", ""]
    if S:
        z += ["Standorte: " + ", ".join(s["name"] + (f" ({s['adresse']})" if s.get("adresse") else "") + ("" if s.get("verkaufbar", True) else ", zählt nicht zum Bestand")
                                         for s in S) + ". „–“ heißt: dort noch nicht gezählt.", ""]
    for k in dict.fromkeys(t["kategorie"] for t in T):
        z += [f"## {k}", "", "| Teil | Menge | Details | Ort | Projekte |", "|---|---|---|---|---|"]
        z += [f"| {_zelle(t['name'] + (' (' + t['artnr'] + ')' if t.get('artnr') else ''))} | {_zelle(menge_text(t) + (' (' + orte_text(S, t) + ')' if orte_text(S, t) else ''))} | "
              f"{_zelle(t.get('beschreibung'))} | {_zelle(t.get('ort'))} | {_zelle(', '.join(t.get('projekte') or []))} |" for t in T if t["kategorie"] == k]
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
ORT_VOR = r"(?:(?<!\S)(?:im|in|ins|aus|vom|von|am|zum|zur|dem|den|der|das)\s+){0,3}"   # begrenzt: viele Füllwörter kosten sonst Sekunden


def verstehen(text):
    """Macht aus einem Satz einen Vorschlag. Gebucht wird nichts. Ein Standort im Satz („im Lager“, „Laden“) steht in „standort“,
    eine Artikelnummer findet das Teil."""
    s = " ".join(str(text or "").split())
    if not s:
        raise ValueError("Was soll ich eintragen?")
    if len(s) > 300:
        raise ValueError("Der Satz ist zu lang. Ein Satz wie „3 Stück Schrauben M4 entnommen“ reicht.")
    with _sperre:
        d = _lesen()
    T = [t for t in d["teile"] if not t.get("entfernt")]
    ort = ""
    for o in sorted((x["name"] for x in _standorte(d)), key=len, reverse=True):   # nur als ganzes Wort, nicht in „Lager-Regal“
        m = re.search(ORT_VOR + r"(?<!\S)" + re.escape(o) + r"(?=[\s?!.,;:]|$)", s, re.I)
        if m:
            ort, s_rest = o, " ".join((s[:m.start()] + " " + s[m.end():]).split())
            break
    else:
        s_rest = s

    def treffer(name):
        n = _norm(name)
        if not n:
            return []
        nr = [t for t in T if t.get("artnr") and _norm(t["artnr"]) == n]
        gleich = nr or [t for t in T if _norm(t["name"]) == n]
        return gleich or [t for t in T if n in _norm(t["name"]) or _norm(t["name"]) in n]

    m = re.match(r"^\s*(?:wie\s*viele?|wieviele?|wie\s*viel|haben\s*wir|habe\s*ich|bestand(?:\s*von)?)\s+(.+?)(?:\s+(?:habe ich|haben wir|sind da|da|noch))?\s*\??\s*$", s_rest, re.I)
    if m:
        return {"art": "frage", "text": s, "suche": m.group(1), "treffer": treffer(m.group(1)), "standort": ort}
    richtung = -1 if re.search(r"\b" + WEG + r"\b", s_rest, re.I) else 1 if re.search(r"\b" + DAZU + r"\b", s_rest, re.I) else 0
    rest = re.sub(r"\b(" + DAZU[1:-1] + "|" + WEG[1:-1] + r")\b", " ", s_rest, flags=re.I).strip(" .!")
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
    return {"art": "buchung", "text": s, "richtung": richtung or 1, "richtung_sicher": bool(richtung), "menge": menge, "einheit": einheit, "name": name,
            "treffer": L, "neu": not L, "standort": ort}
