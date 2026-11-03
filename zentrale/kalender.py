"""Zentrale: Kalender (Seite „Kalender“).

Eigene Termine liegen in DATEN/termine.json und gehen ohne Konto. Wer will, verbindet zusätzlich einen Kalender über CalDAV:
iCloud oder einen anderen Anbieter, der CalDAV kann (viele Hoster und eigene Server). Google und Microsoft bieten dafür keinen
Zugang mit App-Passwort.

Verbinden darf nur der Besitzer, in der Oberfläche. Konto und App-Passwort stehen nur in DATEN/kalender.json und werden nie
über die Schnittstelle herausgegeben, auch nicht an Agenten. Die Zentrale liest die Termine (REPORT mit Zeitraum, Wiederholungen
löst der Kalender auf) und legt neue an (PUT einer .ics-Datei). Im verbundenen Kalender wird nichts geändert und nichts gelöscht.

Zeitzonen: Unter Windows fehlt oft die Zeitzonen-Datenbank, und installiert wird nichts. Darum rechnet die Zentrale in die
Ortszeit des Rechners (astimezone) und nimmt eine genannte Zone nur, wenn Python sie kennt.
"""
import base64
import json
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone

import hub

DATEI = hub.STATE_DIR / "kalender.json"
TERMINE = hub.STATE_DIR / "termine.json"
DIENSTE = {
    "icloud": {"name": "iCloud", "url": "https://caldav.icloud.com/", "hilfe": "appleid.apple.com → Anmelden und Sicherheit → App-spezifische Passwörter"},
    "andere": {"name": "Anderer Kalender (CalDAV)", "url": "", "hilfe": "Adresse und App-Passwort stehen in der Hilfe deines Anbieters"},
}
NS = {"d": "DAV:", "c": "urn:ietf:params:xml:ns:caldav", "a": "http://apple.com/ns/ical/"}
ID = re.compile(r"^[0-9a-f]{6}$")
LOKAL = "lokal"
LOKAL_NAME = "Eigene Termine"
_sperre = threading.Lock()


def _konf():
    try:
        return json.loads(DATEI.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        raise ValueError("Die Kalender-Einstellungen lassen sich gerade nicht lesen. Es wird nichts überschrieben.")


def _lokal():
    try:
        return json.loads(TERMINE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"termine": []}
    except (OSError, ValueError):
        raise ValueError("Die Termine lassen sich gerade nicht lesen. Es wird nichts überschrieben.")


# ---------- Verbindung ----------

def _adresse_ok(url):
    """Zugangsdaten nur über HTTPS (auf diesem Rechner auch ohne, z. B. für einen eigenen Dienst)."""
    t = urllib.parse.urlsplit(url)
    return t.scheme == "https" and bool(t.hostname) or (t.scheme == "http" and t.hostname in ("127.0.0.1", "localhost", "::1"))


def _hauptname(url):
    h = urllib.parse.urlsplit(url).hostname or ""
    return h if re.fullmatch(r"[\d.]+|.*:.*", h) else ".".join(h.split(".")[-2:])


class _KeineUmleitung(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):   # jede Umleitung prüft _dav selbst, sonst ginge das Passwort an die neue Adresse
        return None


_oeffner = urllib.request.build_opener(_KeineUmleitung)


def _dav(methode, url, body=None, tiefe=None, k=None, kopf=None, tiefe_umleitung=0):
    k = k or _konf()
    if not k.get("konto"):
        raise ValueError("Es ist kein Kalender verbunden.")
    name = DIENSTE.get(k.get("dienst"), DIENSTE["andere"])["name"]
    h = {"Authorization": "Basic " + base64.b64encode(f"{k['konto']}:{k['passwort']}".encode("utf-8")).decode(),
         "Content-Type": "application/xml; charset=utf-8", "User-Agent": "Zentrale"}
    if tiefe is not None:
        h["Depth"] = str(tiefe)
    h.update(kopf or {})
    req = urllib.request.Request(url, data=body.encode("utf-8") if isinstance(body, str) else body, method=methode, headers=h)
    try:
        with _oeffner.open(req, timeout=20) as r:
            return r.status, r.read().decode("utf-8", "replace"), r.geturl()
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise ValueError(f"{name} hat die Anmeldung abgelehnt. Konto und App-Passwort prüfen.")
        if e.code in (301, 302, 307, 308) and e.headers.get("Location"):
            ziel = urllib.parse.urljoin(url, e.headers["Location"])
            # nur auf derselben Hauptadresse (iCloud leitet auf eigene Unteradressen um), nie zu Fremden
            if tiefe_umleitung >= 5 or not _adresse_ok(ziel) or _hauptname(ziel) != _hauptname(url):
                raise ValueError(f"{name} leitet auf eine fremde Adresse um. Abgebrochen, das Passwort geht nicht dorthin.")
            return _dav(methode, ziel, body, tiefe, k, kopf, tiefe_umleitung + 1)
        raise ValueError(f"{name} antwortet mit Fehler {e.code}.")
    except OSError as e:
        raise ValueError(f"{name} ist nicht erreichbar: {e}")


def _xml(text):
    try:
        return ET.fromstring(text)
    except ET.ParseError:
        raise ValueError("Der Kalender hat keine lesbare Antwort geschickt. Stimmt die Adresse?")


def _href(xmltext, pfad):
    e = _xml(xmltext).find(pfad, NS)
    return e.text.strip() if e is not None and e.text else ""


def _kalender_finden(k):
    _, x, url = _dav("PROPFIND", k["url"], '<d:propfind xmlns:d="DAV:"><d:prop><d:current-user-principal/></d:prop></d:propfind>', 0, k)
    pr = _href(x, ".//d:current-user-principal/d:href")
    if not pr:
        raise ValueError("Unter dieser Adresse wurde kein Kalender-Konto gefunden.")
    _, x, url = _dav("PROPFIND", urllib.parse.urljoin(url, pr), '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop><c:calendar-home-set/></d:prop></d:propfind>', 0, k)
    home = _href(x, ".//c:calendar-home-set/d:href")
    if not home:
        raise ValueError("Dieses Konto hat keine Kalender.")
    _, x, url = _dav("PROPFIND", urllib.parse.urljoin(url, home), '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav" xmlns:a="http://apple.com/ns/ical/">'
                     '<d:prop><d:displayname/><d:resourcetype/><c:supported-calendar-component-set/><a:calendar-color/></d:prop></d:propfind>', 1, k)
    L = []
    for r in _xml(x).findall("d:response", NS):
        if r.find(".//d:resourcetype/c:calendar", NS) is None:
            continue
        komp = [e.get("name") for e in r.findall(".//c:supported-calendar-component-set/c:comp", NS)]
        if komp and "VEVENT" not in komp:
            continue
        n, farbe = r.find(".//d:displayname", NS), r.find(".//a:calendar-color", NS)
        L.append({"url": urllib.parse.urljoin(url, r.find("d:href", NS).text.strip()), "name": ((n.text or "").strip() if n is not None else "") or "Kalender",
                  "farbe": (farbe.text or "")[:7] if farbe is not None and farbe.text else ""})
    return L


def stand():
    """Für Seite und Agenten: nie Konto und Passwort, Agenten sehen die Adressen der Kalender nicht."""
    k = _konf()
    return {"verbunden": bool(k.get("konto")), "dienst": k.get("dienst", ""), "dienste": DIENSTE, "lokal_name": LOKAL_NAME,
            "kalender": [{"name": c["name"], "farbe": c.get("farbe", ""), "id": str(i)} for i, c in enumerate(k.get("kalender", []))],
            "ziel": _ziel_id(k), "ziel_name": k.get("ziel_name", LOKAL_NAME) or LOKAL_NAME}


def _ziel_id(k):
    return next((str(i) for i, c in enumerate(k.get("kalender", [])) if c["url"] == k.get("ziel")), LOKAL)


def stand_besitzer():
    k = _konf()
    return dict(stand(), konto=k.get("konto", ""))


def einrichten(dienst, konto, passwort, url=None):
    konto, passwort, url = str(konto or "").strip(), re.sub(r"\s+", "", str(passwort or "")), str(url or "").strip()
    if dienst not in DIENSTE:
        raise ValueError("Unbekannter Kalender.")
    if not konto or not passwort:
        raise ValueError("Bitte Konto und App-Passwort eintragen.")
    if dienst == "icloud":
        url = DIENSTE["icloud"]["url"]
        if not re.fullmatch(r"[a-z]{4}-?[a-z]{4}-?[a-z]{4}-?[a-z]{4}", passwort):
            raise ValueError("Das sieht nicht wie ein App-Passwort aus (vier Gruppen à vier Buchstaben, z. B. abcd-efgh-ijkl-mnop). Das normale Apple-Passwort geht hier nicht.")
    if not _adresse_ok(url):
        raise ValueError("Die Adresse muss mit https:// anfangen, sonst wäre das Passwort mitlesbar.")
    k = {"dienst": dienst, "konto": konto, "passwort": passwort, "url": url}
    L = _kalender_finden(k)
    if not L:
        raise ValueError("In diesem Konto wurde kein Kalender gefunden.")
    ziel = next((c for c in L if c["name"].lower() in ("kalender", "home", "privat", "calendar", "zuhause", "personal")), L[0])
    with _sperre:
        hub.json_schreiben(DATEI, {**k, "kalender": L, "ziel": ziel["url"], "ziel_name": ziel["name"], "seit": int(time.time())}, geheim=True)
    return stand_besitzer()


def waehlen(kid):
    """Wohin neue Termine kommen: eine Nummer aus stand()["kalender"] oder „lokal“."""
    with _sperre:
        k = _konf()
        if kid == LOKAL:
            k.update({"ziel": LOKAL, "ziel_name": LOKAL_NAME})
        else:
            L = k.get("kalender", [])
            if not str(kid).isdigit() or int(kid) >= len(L):
                raise ValueError("Diesen Kalender gibt es nicht.")
            k.update({"ziel": L[int(kid)]["url"], "ziel_name": L[int(kid)]["name"]})
        hub.json_schreiben(DATEI, k, geheim=True)
    return stand_besitzer()


def trennen():
    """Zugang vergessen. Die eigenen Termine bleiben, im verbundenen Kalender ändert sich nichts."""
    with _sperre:
        if DATEI.exists():
            hub.json_schreiben(DATEI, {}, geheim=True)
    return stand_besitzer()


# ---------- Termine lesen ----------

def _zone(name):
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:   # Zone unbekannt oder keine Datenbank (Windows): gilt als Ortszeit des Rechners
        return None


def _zeit(wert, parameter):
    """ICS-Zeit → (datetime in Ortszeit oder date, ganztägig?)."""
    wert = wert.strip()
    if "VALUE=DATE" in parameter and "DATE-TIME" not in parameter or re.fullmatch(r"\d{8}", wert):
        return date(int(wert[:4]), int(wert[4:6]), int(wert[6:8])), True
    d = datetime.strptime(wert[:15], "%Y%m%dT%H%M%S")
    if wert.endswith("Z"):
        d = d.replace(tzinfo=timezone.utc)
    else:
        m = re.search(r"TZID=([^;:]+)", parameter)
        z = _zone(m.group(1).strip('"')) if m else None
        if z:
            d = d.replace(tzinfo=z)
    return d.astimezone().replace(tzinfo=None), False


def _ereignisse(ics, kalender):
    out, e, tiefe = [], None, 0
    for z in re.sub(r"\r?\n[ \t]", "", ics).splitlines():
        if z == "BEGIN:VEVENT":
            e, tiefe = {}, 0
        elif z == "END:VEVENT" and e is not None:
            if "start" in e and not e.pop("abgesagt", False):
                out.append(e)
            e = None
        elif e is not None and z.startswith("BEGIN:"):   # VALARM hat eigene Felder (SUMMARY), die gehören nicht zum Termin
            tiefe += 1
        elif e is not None and z.startswith("END:"):
            tiefe -= 1
        elif e is not None and not tiefe and ":" in z:
            kopf, wert = z.split(":", 1)
            name, _, param = kopf.partition(";")
            wert = re.sub(r"\\([nN,;\\])", lambda m: "\n" if m.group(1) in "nN" else m.group(1), wert)
            if name == "SUMMARY":
                e["titel"] = wert
            elif name == "LOCATION":
                e["ort"] = wert
            elif name == "STATUS" and wert.strip().upper() == "CANCELLED":
                e["abgesagt"] = True
            elif name in ("DTSTART", "DTEND"):
                try:
                    t, ganz = _zeit(wert, param)
                except (ValueError, OverflowError, OSError):
                    continue
                e["start" if name == "DTSTART" else "ende"] = t.isoformat()
                if name == "DTSTART":
                    e["ganztag"] = ganz
    for x in out:
        x.setdefault("titel", "(ohne Titel)")
        x["kalender"] = kalender
    return out


def termine(von=None, tage=7):
    """Eigene und verbundene Termine im Zeitraum. Ein Kalender, der gerade nicht antwortet, steht in „fehler“."""
    von = von or datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    bis = von + timedelta(days=max(1, min(int(tage), 62)))
    alle, fehler, k = [], [], _konf()
    with _sperre:
        T = _lokal()["termine"]
    for t in T:
        if not t.get("entfernt") and t["start"] < bis.isoformat() and (t.get("ende") or t["start"])[:10] >= von.date().isoformat():
            alle.append(dict(t, kalender=LOKAL_NAME, lokal=True))
    if k.get("konto"):
        f = lambda d: d.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        body = ('<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop><c:calendar-data>'
                f'<c:expand start="{f(von)}" end="{f(bis)}"/></c:calendar-data></d:prop><c:filter><c:comp-filter name="VCALENDAR">'
                f'<c:comp-filter name="VEVENT"><c:time-range start="{f(von)}" end="{f(bis)}"/></c:comp-filter></c:comp-filter></c:filter></c:calendar-query>')
        for c in k.get("kalender", []):
            try:
                _, x, _ = _dav("REPORT", c["url"], body, 1, k)
                for d in _xml(x).findall(".//c:calendar-data", NS):
                    alle += _ereignisse(d.text or "", c["name"])
            except ValueError as e:
                fehler.append(f"{c['name']}: {e}")
    alle.sort(key=lambda e: e["start"])
    return {"von": von.isoformat(), "bis": bis.isoformat(), "termine": alle, "fehler": fehler}


# ---------- Termin anlegen ----------

def _ics_text(t):
    return str(t).replace("\\", "\\\\").replace("\r", "").replace("\n", "\\n").replace(",", chr(92) + ",").replace(";", chr(92) + ";")


def _zeiten(b):
    """Beginn und Ende aus einer Anfrage (date, date) oder (datetime, datetime) in Ortszeit, ohne Zone."""
    ganz = bool(b.get("ganztag"))
    try:
        if ganz:
            s = date.fromisoformat(str(b.get("start"))[:10])
            return s, date.fromisoformat(str(b.get("ende"))[:10]) if b.get("ende") else s, True
        lies = lambda v: datetime.fromisoformat(str(v).strip().replace(" ", "T").replace("Z", "+00:00"))
        s = lies(b.get("start"))
        s = s.astimezone().replace(tzinfo=None) if s.tzinfo else s
        e = lies(b["ende"]) if b.get("ende") else s + timedelta(minutes=int(b.get("dauer") or 60))
        e = e.astimezone().replace(tzinfo=None) if e.tzinfo else e
    except (TypeError, ValueError, OverflowError, OSError) as x:
        raise ValueError(f"Datum oder Uhrzeit verstehe ich nicht ({x}). Format: 2030-10-24 14:00")
    return s, e, False


def termin_neu(von, b):
    titel = str(b.get("titel") or "").strip()[:200]
    if not titel:
        raise ValueError("Titel fehlt")
    s, e, ganz = _zeiten(b)
    if e < s or (e == s and not ganz):
        raise ValueError("Das Ende liegt vor dem Beginn.")
    k, wahl = _konf(), str(b.get("kalender") or "").strip().lower()
    kal = next((c for c in k.get("kalender", []) if wahl and c["name"].lower() == wahl), None)
    if wahl and not kal and wahl not in (LOKAL, LOKAL_NAME.lower()):
        raise ValueError(f"Einen Kalender „{b['kalender']}“ gibt es nicht. Vorhanden: {', '.join([LOKAL_NAME] + [c['name'] for c in k.get('kalender', [])])}")
    ort, notiz = str(b.get("ort") or "").strip()[:200], str(b.get("notiz") or "").strip()[:2000]
    if not kal and (wahl or k.get("ziel", LOKAL) == LOKAL or not k.get("konto")):
        with _sperre:
            d = _lokal()
            da = {t["id"] for t in d["termine"]}
            tid = secrets.token_hex(3)
            while tid in da:
                tid = secrets.token_hex(3)
            t = {"id": tid, "titel": titel, "start": s.isoformat(), "ende": e.isoformat(), "ganztag": ganz, "ort": ort, "notiz": notiz, "von": von, "erstellt": int(time.time())}
            d["termine"].append(t)
            hub.json_schreiben(TERMINE, d)
        return dict(t, kalender=LOKAL_NAME, lokal=True)
    if ganz:
        zeiten = f"DTSTART;VALUE=DATE:{s:%Y%m%d}\r\nDTEND;VALUE=DATE:{e + timedelta(days=1):%Y%m%d}"   # das Ende zählt in ICS nicht mehr mit
    else:
        u = lambda d: d.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        zeiten = f"DTSTART:{u(s)}\r\nDTEND:{u(e)}"
    uid = f"zentrale-{secrets.token_hex(8)}"
    teile = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Zentrale//Kalender//DE", "BEGIN:VEVENT", f"UID:{uid}@zentrale-starter",
             f"DTSTAMP:{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}", zeiten, f"SUMMARY:{_ics_text(titel)}"]
    if ort:
        teile.append(f"LOCATION:{_ics_text(ort)}")
    teile.append(f"DESCRIPTION:{_ics_text((notiz + chr(10) + chr(10) + 'Eingetragen von der Zentrale (' + von + ')').strip())}")
    if b.get("erinnerung") not in (None, "", 0, "0") and not ganz:
        try:
            teile += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_ics_text(titel)}", f"TRIGGER:-PT{abs(int(b['erinnerung']))}M", "END:VALARM"]
        except (TypeError, ValueError):
            raise ValueError("Die Erinnerung ist eine Zahl in Minuten.")
    teile += ["END:VEVENT", "END:VCALENDAR"]
    ziel = (kal["url"] if kal else k["ziel"]).rstrip("/") + f"/{uid}.ics"
    _dav("PUT", ziel, "\r\n".join(teile) + "\r\n", None, k, {"Content-Type": "text/calendar; charset=utf-8", "If-None-Match": "*"})
    return {"titel": titel, "start": s.isoformat(), "ende": e.isoformat(), "ganztag": ganz, "ort": ort, "kalender": kal["name"] if kal else k.get("ziel_name"), "lokal": False}


def termin_weg(tid):
    """Nur eigene Termine, nur markieren. Im verbundenen Kalender löscht die Zentrale nichts."""
    if not ID.match(str(tid or "")):
        raise ValueError("Diesen Termin gibt es nicht.")
    with _sperre:
        d = _lokal()
        t = next((x for x in d["termine"] if x["id"] == tid and not x.get("entfernt")), None)
        if not t:
            raise ValueError("Diesen Termin gibt es nicht.")
        t["entfernt"] = int(time.time())
        hub.json_schreiben(TERMINE, d)
    return t
