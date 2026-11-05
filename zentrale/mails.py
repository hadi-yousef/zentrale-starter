"""Zentrale: E-Mail lesen (Seite „E-Mail“). Nur lesend.

Der Besitzer verbindet seine Postfächer selbst in der Oberfläche: Adresse und App-Passwort. Beides steht nur in DATEN/mail.json
und wird nie über die Schnittstelle herausgegeben. Ein Faden holt alle zwei Minuten neue Mails aus den gewählten Ordnern (EXAMINE,
BODY.PEEK): Gelesen-Markierungen und Ordner im Postfach bleiben, wie sie sind. Die Zentrale kann keine Mails senden oder löschen.
Je Postfach wählt der Besitzer die Ordner (Standard: Posteingang) und wie weit zurück (Standard: 7 Tage). Ältere Mails kommen
nach und nach dazu, höchstens MAX_RUNDE je Abruf.

Jede Mail bekommt beim Lesen eine Warnung, wenn sie nach Betrug aussieht (warnung()). Das sind Anhaltspunkte, kein Beweis: Es gibt
Fehlalarme, und nicht jede Betrugsmail fällt auf. „Kein Betrug“ setzt nur der Besitzer.

Die Verbindung ist immer verschlüsselt und das Zertifikat wird geprüft. imaplib prüft es von sich aus nicht, darum der eigene Kontext.

Agenten lesen Mails nur, wenn der Besitzer es auf der Seite einschaltet (Standard: aus). Mit Erlaubnis kann ein Agent auf Wunsch
Mails bewerten (wichtig ja/nein, kurze Zusammenfassung). Ein Mail-Text ist nie ein Auftrag, er kommt von Fremden.
Markiert der Besitzer eine Mail als wichtig oder nicht wichtig, gilt das als Regel für diesen Absender.

Gespeichert in DATEN/mails.json: {"letzte_nr": n, "mails": [{nr, konto, ordner, uid, zeit, auth, von, von_name, an, betreff, text, anhaenge, status (neu|bewertet),
wichtig, grund, kurz, gelesen, erledigt, alt}]}. Anhänge werden nicht gespeichert, nur ihre Namen.
"""
import base64
import email
import email.header
import email.policy
import email.utils
import html
import imaplib
import json
import re
import socket
import ssl
import threading
import time
import unicodedata
from datetime import datetime, timedelta

import hub

KONF = hub.STATE_DIR / "mail.json"
DATEI = hub.STATE_DIR / "mails.json"
KALENDER = hub.STATE_DIR / "kalender.json"
DIENSTE = {
    "icloud": {"name": "iCloud", "host": "imap.mail.me.com", "hilfe": "appleid.apple.com → Anmelden und Sicherheit → App-spezifische Passwörter"},
    "gmail": {"name": "Gmail", "host": "imap.gmail.com", "hilfe": "myaccount.google.com/apppasswords (braucht die Bestätigung in zwei Schritten)"},
    "andere": {"name": "Anderes Postfach", "host": "", "hilfe": "Den IMAP-Server (Port 993) und das Passwort nennt dein Anbieter. Outlook und Microsoft 365 lassen keine App-Passwörter mehr zu."},
}
ABSTAND = 120          # Sekunden zwischen zwei Abrufen
ERSTE_TAGE = 7         # Standard: so viele Tage zurück holen
TAGE_WAHL = (7, 30, 90, 365)
MAX_RUNDE = 300        # höchstens so viele Mails je Postfach und Abruf, der Rest kommt beim nächsten
MAX_ORDNER = 20
MAX_KONTEN = 10
MAX_MAILS = 5000
MAX_TEXT = 20000
MAX_GROESSE = 4 * 1024 * 1024   # größere Mails: nur Kopf und Anfang des Textes
HOST = re.compile(r"^(?=.{1,253}$)[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$", re.I)
_sperre = threading.Lock()
_abruf = threading.Event()   # sofort abrufen (nach dem Verbinden)


# ---------- Speicher ----------

def _lesen(datei, leer):
    try:
        return json.loads(datei.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return leer
    except (OSError, ValueError):
        raise ValueError(f"{datei.name} lässt sich gerade nicht lesen. Es wird nichts überschrieben.")


def _konf():
    return _lesen(KONF, {"konten": {}, "regeln": {}})


def _konf_schreiben(k):
    hub.json_schreiben(KONF, k, geheim=True)


def _mails():
    return _lesen(DATEI, {"mails": []})


def _mails_schreiben(d):
    hub.json_schreiben(DATEI, d, geheim=True)


def darf(aid):
    """Der Besitzer immer, Agenten nur mit seiner Erlaubnis."""
    if aid != hub.BESITZER and not _konf().get("agenten_lesen"):
        raise PermissionError("Mails liest ein Agent nur, wenn der Besitzer es auf der Seite „E-Mail“ einschaltet. Frag ihn, statt es zu umgehen.")


# ---------- Postfächer verbinden ----------

def _imap(host, adresse, passwort):
    name = host
    try:
        c = imaplib.IMAP4_SSL(host, 993, ssl_context=ssl.create_default_context(), timeout=40)
    except ssl.SSLError as e:
        raise ValueError(f"Das Zertifikat von {name} stimmt nicht. Es wurde nichts gesendet. ({e})")
    except (OSError, socket.timeout) as e:
        raise ValueError(f"{name} ist nicht erreichbar: {e}")
    try:
        c.login(adresse, passwort)
    except imaplib.IMAP4.error:
        try:
            c.logout()
        except Exception:
            pass
        raise ValueError(f"{name} hat die Anmeldung abgelehnt. Adresse und App-Passwort prüfen.")
    return c


def stand():
    """Für die Seite: verbundene Postfächer ohne Passwörter."""
    k = _konf()
    konten = [{"id": i, "art": x["art"], "name": DIENSTE[x["art"]]["name"], "adresse": x["adresse"], "host": x["host"], "zuletzt": x.get("zuletzt"), "fehler": x.get("fehler", ""),
               "tage": _tage(x), "ordner": [{"id": o, "name": ordner_name(o)} for o in _ordner(x)], "nachholen": _holt_nach(x)}
              for i, x in sorted((k.get("konten") or {}).items())]
    kal = _lesen(KALENDER, {})
    return {"konten": konten, "dienste": DIENSTE, "kalender_zugang": kal.get("dienst") == "icloud" and bool(kal.get("konto")),
            "agenten_lesen": bool(k.get("agenten_lesen")), "regeln": len(k.get("regeln") or {}), "tage_wahl": TAGE_WAHL}


def _tage(x):
    return int(x.get("tage") or ERSTE_TAGE)


def _ordner(x):
    return list(x.get("ordner") or ["INBOX"])


def _zustand(x):
    """Stand je Ordner: {uid: höchste gesehene, validity, bis: bis hierhin nachgeholt, fertig: für so viele Tage vollständig}."""
    st = dict(x.get("stand") or {})
    if not st and x.get("uid"):   # ältere Fassung: nur der Posteingang, die ersten 7 Tage sind schon da
        st["INBOX"] = {"uid": int(x["uid"]), "validity": x.get("uidvalidity", ""), "bis": None, "fertig": ERSTE_TAGE}
    return st


def _holt_nach(x):
    st = _zustand(x)
    return any((st.get(o) or {}).get("fertig", 0) < _tage(x) for o in _ordner(x))


def ordner_name(roh):
    """Ordnernamen kommen im IMAP-eigenen UTF-7: „Entw&APw-rfe“ ist „Entwürfe“."""
    if str(roh).upper() == "INBOX":
        return "Posteingang"

    def teil(m):
        t = m.group(1)
        if not t:
            return "&"
        t = t.replace(",", "/")
        try:
            return base64.b64decode(t + "=" * (-len(t) % 4)).decode("utf-16-be")
        except (ValueError, UnicodeError):
            return m.group(0)
    return re.sub(r"&([^-]*)-", teil, str(roh))


def _q(ordner):
    return "INBOX" if ordner.upper() == "INBOX" else '"' + ordner.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _ordner_lesen(zeilen):
    """Antwort von LIST in eine Liste. Ordner, die man nicht öffnen kann, fallen weg."""
    A = []
    for z in zeilen or []:
        if isinstance(z, tuple):   # langer Name: kommt als eigener Block
            z = re.sub(rb"\{\d+\}\s*$", b"", z[0]) + b'"' + z[1].replace(b"\\", b"\\\\").replace(b'"', b'\\"') + b'"'
        m = re.match(rb'^\((.*?)\)\s+(?:"(?:[^"\\]|\\.)*"|NIL)\s+(.+)$', z or b"", re.S)
        if not m or b"\\noselect" in m.group(1).lower():
            continue
        roh = m.group(2).strip().decode("utf-8", "replace")
        if roh.startswith('"') and roh.endswith('"') and len(roh) > 1:
            roh = re.sub(r"\\(.)", r"\1", roh[1:-1])
        if roh and not re.search(r"[\x00-\x1f]", roh):
            fl = m.group(1).lower()
            A.append({"id": roh, "name": ordner_name(roh), "art": next((a for a, f in (("Papierkorb", b"\\trash"), ("Werbung", b"\\junk"), ("Entwürfe", b"\\drafts"), ("Gesendet", b"\\sent")) if f in fl), "")})
    return sorted(A, key=lambda o: (o["id"].upper() != "INBOX", o["name"].lower()))


def ordner_liste(kid):
    """Die Ordner eines Postfachs, zum Auswählen. Nur der Besitzer, in der Oberfläche."""
    x = (_konf().get("konten") or {}).get(str(kid or "").lower())
    if not x:
        raise ValueError("Dieses Postfach gibt es nicht.")
    c = _imap(x["host"], x["adresse"], x["passwort"])
    try:
        typ, z = c.list()
        if typ != "OK":
            raise ValueError("Die Ordner lassen sich nicht lesen.")
        return {"ordner": _ordner_lesen(z), "gewaehlt": _ordner(x)}
    finally:
        try:
            c.logout()
        except Exception:
            pass


def einstellen(kid, b):
    """Wie weit zurück und welche Ordner. Nur der Besitzer. Ordner nur aus dem, was das Postfach selbst nennt."""
    kid = str(kid or "").lower()
    if "ordner" in b:
        wahl = [str(o) for o in (b.get("ordner") or [])]
        if not wahl:
            raise ValueError("Mindestens ein Ordner muss bleiben.")
        if len(wahl) > MAX_ORDNER:
            raise ValueError(f"Höchstens {MAX_ORDNER} Ordner je Postfach.")
        da = {o["id"] for o in ordner_liste(kid)["ordner"]} | {"INBOX"}
        if [o for o in wahl if o not in da]:
            raise ValueError("Diesen Ordner gibt es im Postfach nicht.")
    if "tage" in b:
        try:
            tage = int(b.get("tage"))
        except (TypeError, ValueError):
            tage = 0
        if tage not in TAGE_WAHL:
            raise ValueError("Zeitraum bitte aus der Liste wählen.")
    with _sperre:
        k = _konf()
        x = (k.get("konten") or {}).get(kid)
        if not x:
            raise ValueError("Dieses Postfach gibt es nicht.")
        if "ordner" in b:
            x["stand"] = _zustand(x)
            x["ordner"] = wahl
        if "tage" in b:
            x["stand"] = _zustand(x)
            x["tage"] = tage
        _konf_schreiben(k)
    _abruf.set()
    return stand()


def verbinden(art, adresse=None, passwort=None, host=None, vom_kalender=False, tage=None):
    if art not in DIENSTE:
        raise ValueError("Unbekanntes Postfach.")
    try:
        tage = int(tage) if tage else None
    except (TypeError, ValueError):
        tage = 0
    if tage is not None and tage not in TAGE_WAHL:
        raise ValueError("Zeitraum bitte aus der Liste wählen.")
    if vom_kalender:
        kal = _lesen(KALENDER, {})
        if art != "icloud" or kal.get("dienst") != "icloud" or not kal.get("konto"):
            raise ValueError("Den Zugang des Kalenders gibt es nur für iCloud, und nur, wenn der Kalender verbunden ist.")
        adresse, passwort = kal.get("konto"), kal.get("passwort")
    adresse, passwort = str(adresse or "").strip(), re.sub(r"\s+", "", str(passwort or ""))
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", adresse, re.I) or not passwort:
        raise ValueError("Bitte E-Mail-Adresse und App-Passwort eintragen.")
    host = DIENSTE[art]["host"] or str(host or "").strip().lower()
    if not HOST.match(host):
        raise ValueError("Bitte den IMAP-Server eintragen, z. B. imap.beispiel.at.")
    c = _imap(host, adresse, passwort)
    try:
        c.logout()
    except Exception:
        pass
    with _sperre:
        k = _konf()
        K = k.setdefault("konten", {})
        if adresse.lower() not in K and len(K) >= MAX_KONTEN:
            raise ValueError(f"Höchstens {MAX_KONTEN} Postfächer.")
        alt = K.get(adresse.lower()) or {}   # neues Passwort: gewählte Ordner und der Stand bleiben, nichts wird doppelt geholt
        K[adresse.lower()] = {"art": art, "host": host, "adresse": adresse, "passwort": passwort, "seit": alt.get("seit") or int(time.time()), "zuletzt": None, "fehler": "",
                              "tage": tage or _tage(alt), "ordner": _ordner(alt), "stand": _zustand(alt)}
        _konf_schreiben(k)
    _abruf.set()
    return stand()


def trennen(kid):
    """Postfach vergessen. Schon geholte Mails bleiben in der Zentrale."""
    with _sperre:
        k = _konf()
        (k.get("konten") or {}).pop(str(kid or "").lower(), None)
        _konf_schreiben(k)
    return stand()


def agenten_erlauben(ja):
    with _sperre:
        k = _konf()
        k["agenten_lesen"] = bool(ja)
        _konf_schreiben(k)
    return stand()


# ---------- Mails lesen ----------

def _sauber(t):
    """Kaputte Bytes aus fremden Mails dürfen das Speichern nie stören."""
    return str(t).encode("utf-8", "replace").decode("utf-8")


def _kopf(v):
    try:
        return _sauber(email.header.make_header(email.header.decode_header(str(v or "")))).strip()
    except Exception:
        return _sauber(v or "").strip()


def _html_text(h):
    h = re.sub(r"(?is)<(script|style|head)[^>]*>.*?</\1>", " ", h)
    h = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</h\d>|</li>", "\n", h)
    t = html.unescape(re.sub(r"<[^>]+>", " ", h))
    t = re.sub(r"[ \t ]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n\n", t).strip()


def _text(msg):
    """Lesbarer Text: text/plain bevorzugt, sonst HTML ohne Auszeichnung. Dazu die Namen der Anhänge."""
    plain, htm, anh = [], [], []
    for teil in msg.walk() if msg.is_multipart() else [msg]:
        if teil.is_multipart():
            continue
        name = teil.get_filename()
        if name or teil.get_content_disposition() == "attachment":
            anh.append(_kopf(name or "Anhang")[:120])
            continue
        typ = teil.get_content_type()
        if typ not in ("text/plain", "text/html"):
            continue
        try:
            inhalt = teil.get_content()
        except Exception:
            roh = teil.get_payload(decode=True) or b""
            try:
                inhalt = roh.decode(teil.get_content_charset() or "utf-8", "replace")
            except LookupError:
                inhalt = roh.decode("utf-8", "replace")
        (plain if typ == "text/plain" else htm).append(str(inhalt))
    t = "\n\n".join(plain).strip() or _html_text("\n".join(htm))
    t = re.sub(r"\r\n?", "\n", _sauber(t))
    return re.sub(r"\n{3,}", "\n\n", t)[:MAX_TEXT], anh[:30]


def _zerlegen(roh, kid, uid, alt, ordner="INBOX"):
    msg = email.message_from_bytes(roh, policy=email.policy.default)
    name, adr = email.utils.parseaddr(_kopf(msg.get("From")))
    try:
        zeit = int(email.utils.parsedate_to_datetime(msg.get("Date")).timestamp())
    except (TypeError, ValueError, IndexError, OverflowError, OSError):
        zeit = int(time.time())
    text, anh = _text(msg)
    # Nur die oberste Zeile zählt: Sie schreibt der eigene Mail-Anbieter, darunter kann der Absender alles Mögliche hineinschreiben
    auth = msg.get_all("Authentication-Results") or [""]
    return {"konto": kid, "ordner": ordner, "auth": _sauber(auth[0]).lower()[:500], "uid": uid, "zeit": zeit, "von": adr.lower()[:200], "von_name": (name or adr)[:120],
            "an": _kopf(msg.get("To"))[:300], "betreff": _kopf(msg.get("Subject"))[:300] or "(ohne Betreff)", "text": text, "anhaenge": anh,
            "message_id": _sauber(msg.get("Message-ID") or "")[:300], "status": "neu", "wichtig": None, "grund": "", "kurz": "", "gelesen": False, "erledigt": False, "alt": alt}


def _seit(tage):
    seit = datetime.now() - timedelta(days=tage)
    monat = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")[seit.month - 1]   # strftime wäre je nach Sprache des Rechners falsch
    return f"{seit.day:02d}-{monat}-{seit.year}"


def _eine(c, uid, kid, ordner, alt):
    typ, g = c.uid("fetch", str(uid), "(FLAGS RFC822.SIZE)")
    kopf = g[0] if g and isinstance(g[0], bytes) else b""
    m = re.search(rb"RFC822\.SIZE (\d+)", kopf)
    teil = "(BODY.PEEK[])" if (int(m.group(1)) if m else 0) <= MAX_GROESSE else "(BODY.PEEK[HEADER] BODY.PEEK[1]<0.200000>)"
    typ, g = c.uid("fetch", str(uid), teil)
    roh = b"".join(t[1] for t in g if isinstance(t, tuple))
    if not roh:
        return None
    x = _zerlegen(roh, kid, uid, alt, ordner)
    x["gelesen"] = b"\\seen" in kopf.lower()   # im Postfach schon gelesen, z. B. am Handy
    return x


def _ordner_holen(c, ordner, st, tage, kid, platz):
    """Ein Ordner: erst Neues, dann Älteres bis zum gewählten Zeitraum, von neu nach alt. Gibt (mails, neuer Stand) zurück."""
    typ, _ = c.select(_q(ordner), readonly=True)
    if typ != "OK":
        raise ValueError("Der Ordner lässt sich nicht öffnen.")
    validity = (c.untagged_responses.get("UIDVALIDITY") or [b""])[0]
    validity = validity.decode() if isinstance(validity, bytes) else str(validity)
    st = dict(st or {})
    if st.get("validity") != validity:   # neuer Ordner, oder der Anbieter hat die Nummern neu vergeben
        st = {"uid": 0, "validity": validity, "bis": None, "fertig": 0}
    neu = []
    if st.get("uid"):
        typ, d = c.uid("search", None, f"UID {int(st['uid']) + 1}:*")
        uids = sorted(int(u) for u in (d[0] or b"").split() if u.isdigit())
        for uid in [u for u in uids if u > st["uid"]][:max(platz, 0)]:
            x = _eine(c, uid, kid, ordner, False)
            if x:
                neu.append(x)
            st["uid"] = uid
    else:   # auch ohne Mails im Zeitraum ab jetzt nur noch Neues holen
        typ, s = c.status(_q(ordner), "(UIDNEXT)")
        m = re.search(rb"UIDNEXT (\d+)", s[0] if s and s[0] else b"")
        st["uid"] = int(m.group(1)) - 1 if m else 0
    platz -= len(neu)
    if st.get("fertig", 0) < tage and platz > 0:
        typ, d = c.uid("search", None, "SINCE", _seit(tage))
        uids = sorted(int(u) for u in (d[0] or b"").split() if u.isdigit())
        rest = [u for u in uids if u <= st["uid"] and (st.get("bis") is None or u < st["bis"])]
        nimm = rest[-platz:]
        for uid in reversed(nimm):
            x = _eine(c, uid, kid, ordner, True)
            if x:
                neu.append(x)
        if nimm:
            st["bis"] = min(nimm)
        if len(nimm) == len(rest):
            st["fertig"] = tage
    return neu, st


def _holen(x):
    """Neue Mails eines Postfachs. Gibt (mails, stand je ordner, fehler) zurück. readonly: das Postfach bleibt, wie es ist."""
    c = _imap(x["host"], x["adresse"], x["passwort"])
    try:
        st, neu, fehler = _zustand(x), [], ""
        for o in _ordner(x):
            try:   # ein Ordner, der nicht geht, darf die anderen nicht aufhalten
                n, st[o] = _ordner_holen(c, o, st.get(o), _tage(x), x["adresse"].lower(), MAX_RUNDE - len(neu))
                neu += n
            except (ValueError, OSError, imaplib.IMAP4.error, socket.timeout) as e:
                fehler = f"{ordner_name(o)}: {e}"[:300]
        return neu, st, fehler
    finally:
        try:
            c.logout()
        except Exception:
            pass


def _einsortieren(k, neu):
    """Neue Mails speichern (ohne Doppelte), mit den Regeln des Besitzers je Absender. Unter der Sperre aufrufen."""
    d = _mails()
    def schluessel(m):
        ordner = m.get("ordner") or "INBOX"
        return m["konto"], m.get("message_id") or (m["uid"] if ordner == "INBOX" else f"{ordner}:{m['uid']}")
    da = {schluessel(m) for m in d["mails"]}
    nr = max([m["nr"] for m in d["mails"]] + [d.get("letzte_nr") or 0])
    regeln = k.get("regeln") or {}
    for m in sorted(neu, key=lambda m: m["zeit"]):
        if schluessel(m) in da:
            continue
        da.add(schluessel(m))
        nr += 1
        m["nr"] = nr
        if m["von"] in regeln:
            m.update({"wichtig": bool(regeln[m["von"]]), "grund": "Von dir so festgelegt", "status": "bewertet"})
        d["mails"].append(m)
    d["letzte_nr"] = nr
    d["mails"] = sorted(d["mails"], key=lambda m: m["zeit"])[-MAX_MAILS:]   # nach Zeit: Nachgeholtes ist alt, auch wenn seine Nummer neu ist
    _mails_schreiben(d)


def abrufen():
    """Alle verbundenen Postfächer einmal abrufen."""
    for kid, x in list((_konf().get("konten") or {}).items()):
        try:
            neu, zustand, fehler = _holen(x)
        except (ValueError, OSError, imaplib.IMAP4.error, socket.timeout) as e:
            neu, zustand, fehler = [], _zustand(x), str(e)[:300]
        with _sperre:
            k = _konf()
            y = (k.get("konten") or {}).get(kid)
            if not y:   # in der Zwischenzeit getrennt
                continue
            y.update({"zuletzt": int(time.time()), "fehler": fehler, "stand": zustand})
            _konf_schreiben(k)
            if neu:
                _einsortieren(k, neu)


def waechter():
    while True:
        try:
            if _konf().get("konten"):
                abrufen()
        except Exception as e:   # der Faden darf nie sterben
            print("mails:", e, flush=True)
        _abruf.wait(ABSTAND)
        _abruf.clear()


# ---------- Für Seite und Agenten ----------

# Bekannte Namen und ihre echten Adressen. Betrüger nennen sich so, schreiben aber von woanders.
MARKEN = {"paypal": ("paypal.com", "paypal.de"), "amazon": ("amazon.de", "amazon.com", "amazon.at"), "ebay": ("ebay.de", "ebay.com", "ebay.at"),
          "kleinanzeigen": ("kleinanzeigen.de",), "apple": ("apple.com",), "microsoft": ("microsoft.com", "office.com", "outlook.com"),
          "google": ("google.com", "google.de"), "ionos": ("ionos.de", "ionos.com", "ionos.at"), "dhl": ("dhl.de", "dhl.com", "deutschepost.de"),
          "netflix": ("netflix.com",), "klarna": ("klarna.com", "klarna.de"), "telekom": ("telekom.de", "t-online.de"), "vodafone": ("vodafone.de", "vodafone.com"),
          "shopify": ("shopify.com",)}
DRUCK = ("verifizieren", "verifizierung", "gesperrt", "sperrung", "eingeschränkt", "zertifikat", "läuft ab", "innerhalb von 24", "24 stunden", "passwort bestätigen",
         "zugangsdaten", "konto bestätigen", "kontodaten", "identität bestätigen", "letzte mahnung", "sofort handeln",
         "domain bestätigen", "schließung", "at risk", "verify your", "suspended", "will be closed", "confirm your identity", "within 24 hours")
ZEICHEN = str.maketrans({"ο": "o", "о": "o", "а": "a", "е": "e", "р": "p", "с": "c", "і": "i", "у": "y", "х": "x", "ı": "i", "ł": "l", "ν": "v", "α": "a", "1": "l", "0": "o"})


def _klartext(domain):
    """xn--…-Teile lesbar machen: So sieht man, was dahintersteckt."""
    aus = []
    for t in str(domain).lower().split("."):
        if t.startswith("xn--"):
            try:
                t = t.encode("ascii").decode("idna")
            except (UnicodeError, ValueError):
                pass
        aus.append(t)
    return ".".join(aus)


def _schrift(t):
    """Die Schriften in einem Teil der Adresse (LATIN, GREEK, CYRILLIC …), ohne Ziffern und Bindestriche."""
    return {unicodedata.name(z, "?").split(" ")[0] for z in t if z.isalpha()}


def _gerippe(t):
    """Ohne Akzente und mit den üblichen Doppelgängern: „ιοnos“ und „paypa1“ werden so lesbar verglichen."""
    return "".join(z for z in unicodedata.normalize("NFKD", t.translate(ZEICHEN)) if not unicodedata.combining(z))


def _gehoert(domain, echte):
    return any(domain == e or domain.endswith("." + e) for e in echte)


def warnung(m, vertraut=None):
    """Sieht die Mail nach Betrug aus? {"stufe": "hoch"|"vorsicht", "gruende": […]} oder None. Nur aus dem, was in der Mail steht."""
    if m.get("kein_betrug"):
        return None
    von, name, auth = str(m.get("von") or ""), str(m.get("von_name") or ""), str(m.get("auth") or "")
    roh = von.rsplit("@", 1)[1] if "@" in von else ""
    domain = _klartext(roh)
    hart, leise = [], []
    if "dmarc=fail" in auth or ("spf=fail" in auth and "dkim=fail" in auth):
        hart.append("Dein Mail-Anbieter konnte den Absender nicht bestätigen.")
    if not (vertraut or {}).get(von):
        teile = [t for t in domain.split(".") if t]
        if any(len(_schrift(t)) > 1 for t in teile):
            hart.append(f"Die Adresse mischt Buchstaben aus verschiedenen Schriften und ahmt so eine andere nach: {domain}")
        elif len(teile) > 1 and not teile[-1].isascii() and _gerippe(teile[-1]).isascii():
            hart.append(f"Die Endung der Adresse sieht nur aus wie eine bekannte, sie ist eine andere: {domain}")
        elif teile and teile[-1].isascii() and any(_schrift(t) - {"LATIN"} for t in teile[:-1]):
            hart.append(f"Die Adresse ist in einer fremden Schrift geschrieben und ahmt so eine andere nach: {domain}")
        worte = {w for t in teile for w in re.split(r"-", _gerippe(t))}
        marke = next((x for x, echte in MARKEN.items() if x in worte and not _gehoert(domain, echte)), None)
        if marke:
            hart.append(f"Die Adresse tut so, als käme sie von {marke.capitalize()}, gehört aber nicht dazu: {domain}")
        in_name = re.search(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)", name)
        if in_name and in_name.group(1).lower() != roh.lower():
            hart.append(f"Im Namen steht eine andere Adresse als die, von der die Mail wirklich kommt: {domain}")
        marke = next((x for x, echte in MARKEN.items() if re.search(rf"\b{x}\b", _gerippe(name.lower())) and not _gehoert(domain, echte)), None)
        if marke and not any(marke.capitalize() in h for h in hart):
            hart.append(f"Der Name sagt {marke.capitalize()}, die Mail kommt aber von {domain}")
        eigene = str(m.get("konto") or "").rsplit("@", 1)[-1].lower()
        if domain and domain == eigene and "pass" not in auth:
            (hart if auth else leise).append("Die Mail trägt deine eigene Adresse als Absender, ohne Bestätigung, dass sie wirklich von dort kommt.")
        echt = any(_gehoert(domain, e) for e in MARKEN.values())
        if not echt:
            t = (str(m.get("betreff") or "") + " " + str(m.get("text") or "")[:4000]).lower()
            if sum(1 for w in DRUCK if w in t) >= 2:
                leise.append("Der Text macht Druck (gesperrt, bestätigen, Frist). So schreiben Betrüger oft.")
    if hart:
        return {"stufe": "hoch", "gruende": hart + leise}
    return {"stufe": "vorsicht", "gruende": leise} if leise else None


def _ohne_text(m, vertraut=None):
    return dict({k: v for k, v in m.items() if k not in ("text", "message_id", "auth")}, vorschau=re.sub(r"\s+", " ", m.get("text") or "")[:160],
                ordner_name=ordner_name(m.get("ordner") or "INBOX"), warnung=warnung(m, vertraut))


def _finden(d, nr):
    m = next((x for x in d["mails"] if str(x["nr"]) == str(nr)), None)
    if not m:
        raise ValueError("Diese Mail gibt es nicht.")
    return m


def _zahl(wert, standard, oben):
    try:
        return max(1, min(int(wert or standard), oben))
    except (TypeError, ValueError):
        return standard


def _passt(m, worte):
    t = " ".join(str(m.get(f) or "") for f in ("betreff", "von", "von_name", "an", "kurz", "text")).lower()
    return all(w in t for w in worte)


def liste(anzahl=60, suche="", art="", konto=""):
    """Verdächtige zuerst, dann wichtige, dann die neuesten. Erledigte fallen weg. Mit Suche, Art oder Postfach zusätzlich die Treffer,
    die auch Erledigtes umfassen, und über alle gespeicherten Mails."""
    n = _zahl(anzahl, 60, 500)
    with _sperre:
        A, vertraut = sorted(_mails()["mails"], key=lambda m: -m["zeit"]), _konf().get("vertraut") or {}
    M = [_mit for _mit in A if not _mit.get("erledigt")]
    V = [m for m in M if (warnung(m, vertraut) or {}).get("stufe") == "hoch"]
    nv = {m["nr"] for m in V}
    W = [m for m in M if m.get("wichtig") and m["nr"] not in nv]
    R = [m for m in M if not m.get("wichtig") and m["nr"] not in nv]
    aus = dict(stand(), verdacht=[_ohne_text(m, vertraut) for m in V[:n]], wichtig=[_ohne_text(m, vertraut) for m in W[:n]], rest=[_ohne_text(m, vertraut) for m in R[:n]],
               neu=sum(1 for m in M if not m.get("gelesen")), unbewertet=sum(1 for m in M if m.get("status") == "neu"), gesamt=len(M))
    worte = str(suche or "").lower().split()
    if worte or art or konto:
        filter_ = {"ungelesen": lambda m: not m.get("gelesen") and not m.get("erledigt"), "wichtig": lambda m: m.get("wichtig") and not m.get("erledigt"),
                   "verdacht": lambda m: m["nr"] in nv, "erledigt": lambda m: m.get("erledigt")}.get(art, lambda m: True)
        T = [m for m in A if filter_(m) and (not konto or m["konto"] == str(konto).lower()) and (not worte or _passt(m, worte))]
        aus.update(treffer=[_ohne_text(m, vertraut) for m in T[:n]], treffer_gesamt=len(T))
    return aus


def lesen(nr):
    with _sperre:
        m = _finden(_mails(), nr)
        vertraut = _konf().get("vertraut") or {}
    return dict({k: v for k, v in m.items() if k != "auth"}, ordner_name=ordner_name(m.get("ordner") or "INBOX"), warnung=warnung(m, vertraut))


def aendern(von, nr, b):
    """Gelesen, erledigt, wichtig ja/nein. Beim Besitzer wird „wichtig“ zur Regel für den Absender. „Kein Betrug“ sagt nur der Besitzer."""
    if "kein_betrug" in b and von != hub.BESITZER:
        raise PermissionError("Ob eine Warnung falsch war, entscheidet nur der Besitzer. Sag ihm, was dir auffällt.")
    with _sperre:
        d = _mails()
        m = _finden(d, nr)
        if "kein_betrug" in b:
            m["kein_betrug"] = bool(b["kein_betrug"])
            k = _konf()
            if m["kein_betrug"] and m["von"]:   # gilt auch für spätere Mails dieser Adresse, außer der Anbieter kann sie nicht bestätigen
                k.setdefault("vertraut", {})[m["von"]] = True
            elif m["von"]:
                (k.get("vertraut") or {}).pop(m["von"], None)
            _konf_schreiben(k)
        for f in ("gelesen", "erledigt"):
            if f in b:
                m[f] = bool(b[f])
        if "wichtig" in b:
            m.update({"wichtig": bool(b["wichtig"]), "status": "bewertet", "grund": "Von dir so festgelegt" if von == hub.BESITZER else str(b.get("grund") or "")[:300]})
            if von == hub.BESITZER and m["von"]:
                k = _konf()
                r = k.setdefault("regeln", {})
                r[m["von"]] = m["wichtig"]
                if len(r) > 2000:
                    k["regeln"] = dict(list(r.items())[-2000:])
                _konf_schreiben(k)
        _mails_schreiben(d)
    return _ohne_text(m, _konf().get("vertraut"))


def offen(anzahl=10):
    """Für einen Agenten mit Erlaubnis: unbewertete Mails, die älteste zuerst, mit Text."""
    n = _zahl(anzahl, 10, 30)
    with _sperre:   # erst Neues, die älteste zuerst; Nachgeholtes danach, die neueste zuerst
        M, vertraut = [m for m in _mails()["mails"] if m["status"] == "neu"], _konf().get("vertraut") or {}
    M = (sorted((m for m in M if not m.get("alt")), key=lambda m: m["zeit"]) + sorted((m for m in M if m.get("alt")), key=lambda m: -m["zeit"]))[:n]
    return {"mails": [dict({k: m[k] for k in ("nr", "konto", "zeit", "von", "von_name", "an", "betreff", "anhaenge", "alt")}, text=m["text"][:6000], warnung=warnung(m, vertraut)) for m in M]}


def bewerten(von, nr, b):
    """Urteil eines Agenten. Die Regel des Besitzers für den Absender geht vor."""
    with _sperre:
        d = _mails()
        m = _finden(d, nr)
        regeln = _konf().get("regeln") or {}
        m.update({"status": "bewertet", "wichtig": bool(regeln[m["von"]]) if m["von"] in regeln else bool(b.get("wichtig")),
                  "grund": str(b.get("grund") or "")[:300], "kurz": str(b.get("kurz") or "")[:600], "bewertet_von": von})
        _mails_schreiben(d)
    return _ohne_text(m, _konf().get("vertraut"))
