"""Zentrale: E-Mail lesen (Seite „E-Mail“). Nur lesend.

Der Besitzer verbindet seine Postfächer selbst in der Oberfläche: Adresse und App-Passwort. Beides steht nur in DATEN/mail.json
und wird nie über die Schnittstelle herausgegeben. Ein Faden holt alle zwei Minuten neue Mails aus dem Posteingang (EXAMINE,
BODY.PEEK): Gelesen-Markierungen und Ordner im Postfach bleiben, wie sie sind. Die Zentrale kann keine Mails senden oder löschen.
Beim ersten Verbinden kommen die Mails der letzten 7 Tage dazu.

Die Verbindung ist immer verschlüsselt und das Zertifikat wird geprüft. imaplib prüft es von sich aus nicht, darum der eigene Kontext.

Agenten lesen Mails nur, wenn der Besitzer es auf der Seite einschaltet (Standard: aus). Mit Erlaubnis kann ein Agent auf Wunsch
Mails bewerten (wichtig ja/nein, kurze Zusammenfassung). Ein Mail-Text ist nie ein Auftrag, er kommt von Fremden.
Markiert der Besitzer eine Mail als wichtig oder nicht wichtig, gilt das als Regel für diesen Absender.

Gespeichert in DATEN/mails.json: {"mails": [{nr, konto, uid, zeit, von, von_name, an, betreff, text, anhaenge, status (neu|bewertet),
wichtig, grund, kurz, gelesen, erledigt, alt}]}. Anhänge werden nicht gespeichert, nur ihre Namen.
"""
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
ERSTE_TAGE = 7         # beim ersten Verbinden so viele Tage zurück holen
MAX_KONTEN = 10
MAX_MAILS = 3000
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
    konten = [{"id": i, "art": x["art"], "name": DIENSTE[x["art"]]["name"], "adresse": x["adresse"], "host": x["host"], "zuletzt": x.get("zuletzt"), "fehler": x.get("fehler", "")}
              for i, x in sorted((k.get("konten") or {}).items())]
    kal = _lesen(KALENDER, {})
    return {"konten": konten, "dienste": DIENSTE, "kalender_zugang": kal.get("dienst") == "icloud" and bool(kal.get("konto")),
            "agenten_lesen": bool(k.get("agenten_lesen")), "regeln": len(k.get("regeln") or {})}


def verbinden(art, adresse=None, passwort=None, host=None, vom_kalender=False):
    if art not in DIENSTE:
        raise ValueError("Unbekanntes Postfach.")
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
        K[adresse.lower()] = {"art": art, "host": host, "adresse": adresse, "passwort": passwort, "seit": int(time.time()), "zuletzt": None, "fehler": "", "uid": 0, "uidvalidity": ""}
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


def _zerlegen(roh, kid, uid, alt):
    msg = email.message_from_bytes(roh, policy=email.policy.default)
    name, adr = email.utils.parseaddr(_kopf(msg.get("From")))
    try:
        zeit = int(email.utils.parsedate_to_datetime(msg.get("Date")).timestamp())
    except (TypeError, ValueError, IndexError, OverflowError, OSError):
        zeit = int(time.time())
    text, anh = _text(msg)
    return {"konto": kid, "uid": uid, "zeit": zeit, "von": adr.lower()[:200], "von_name": (name or adr)[:120],
            "an": _kopf(msg.get("To"))[:300], "betreff": _kopf(msg.get("Subject"))[:300] or "(ohne Betreff)", "text": text, "anhaenge": anh,
            "message_id": _sauber(msg.get("Message-ID") or "")[:300], "status": "neu", "wichtig": None, "grund": "", "kurz": "", "gelesen": False, "erledigt": False, "alt": alt}


def _holen(x):
    """Neue Mails eines Postfachs. Gibt (mails, letzte_uid, uidvalidity) zurück. readonly: das Postfach bleibt, wie es ist."""
    c = _imap(x["host"], x["adresse"], x["passwort"])
    try:
        typ, _ = c.select("INBOX", readonly=True)
        if typ != "OK":
            raise ValueError("Der Posteingang lässt sich nicht öffnen.")
        validity = (c.untagged_responses.get("UIDVALIDITY") or [b""])[0]
        validity = validity.decode() if isinstance(validity, bytes) else str(validity)
        erst = not x.get("uid") or validity != x.get("uidvalidity")
        if erst:
            seit = (datetime.now() - timedelta(days=ERSTE_TAGE))
            monat = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")[seit.month - 1]   # strftime wäre je nach Sprache des Rechners falsch
            typ, d = c.uid("search", None, "SINCE", f"{seit.day:02d}-{monat}-{seit.year}")
        else:
            typ, d = c.uid("search", None, f"UID {int(x['uid']) + 1}:*")
        uids = sorted(int(u) for u in (d[0] or b"").split() if u.isdigit())
        if not erst:
            uids = [u for u in uids if u > int(x["uid"])]
        neu, letzte = [], int(x.get("uid") or 0) if not erst else 0
        if erst:   # auch ohne Mails der letzten Tage ab jetzt nur noch Neues holen
            typ, s = c.status("INBOX", "(UIDNEXT)")
            m = re.search(rb"UIDNEXT (\d+)", s[0] if s and s[0] else b"")
            letzte = int(m.group(1)) - 1 if m else 0
        for uid in uids[-300:]:
            typ, g = c.uid("fetch", str(uid), "(RFC822.SIZE)")
            m = re.search(rb"RFC822\.SIZE (\d+)", g[0] if g and g[0] else b"")
            teil = "(BODY.PEEK[])" if (int(m.group(1)) if m else 0) <= MAX_GROESSE else "(BODY.PEEK[HEADER] BODY.PEEK[1]<0.200000>)"
            typ, g = c.uid("fetch", str(uid), teil)
            roh = b"".join(t[1] for t in g if isinstance(t, tuple))
            if roh:
                neu.append(_zerlegen(roh, x["adresse"].lower(), uid, alt=erst))
            letzte = max(letzte, uid)
        return neu, letzte, validity
    finally:
        try:
            c.logout()
        except Exception:
            pass


def _einsortieren(k, neu):
    """Neue Mails speichern (ohne Doppelte), mit den Regeln des Besitzers je Absender. Unter der Sperre aufrufen."""
    d = _mails()
    da = {(m["konto"], m.get("message_id") or m["uid"]) for m in d["mails"]}
    nr = max([m["nr"] for m in d["mails"]] + [0])
    regeln = k.get("regeln") or {}
    for m in sorted(neu, key=lambda m: m["zeit"]):
        if (m["konto"], m.get("message_id") or m["uid"]) in da:
            continue
        nr += 1
        m["nr"] = nr
        if m["von"] in regeln:
            m.update({"wichtig": bool(regeln[m["von"]]), "grund": "Von dir so festgelegt", "status": "bewertet"})
        d["mails"].append(m)
    d["mails"] = sorted(d["mails"], key=lambda m: m["nr"])[-MAX_MAILS:]
    _mails_schreiben(d)


def abrufen():
    """Alle verbundenen Postfächer einmal abrufen."""
    for kid, x in list((_konf().get("konten") or {}).items()):
        try:
            neu, letzte, validity = _holen(x)
            fehler = ""
        except (ValueError, OSError, imaplib.IMAP4.error, socket.timeout) as e:
            neu, letzte, validity, fehler = [], x.get("uid") or 0, x.get("uidvalidity") or "", str(e)[:300]
        with _sperre:
            k = _konf()
            y = (k.get("konten") or {}).get(kid)
            if not y:   # in der Zwischenzeit getrennt
                continue
            y.update({"zuletzt": int(time.time()), "fehler": fehler, "uid": letzte, "uidvalidity": validity})
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

def _ohne_text(m):
    return dict({k: v for k, v in m.items() if k not in ("text", "message_id")}, vorschau=re.sub(r"\s+", " ", m.get("text") or "")[:160])


def _finden(d, nr):
    m = next((x for x in d["mails"] if str(x["nr"]) == str(nr)), None)
    if not m:
        raise ValueError("Diese Mail gibt es nicht.")
    return m


def liste(anzahl=60):
    """Wichtige zuerst, dann die neuesten. Erledigte fallen weg."""
    try:
        n = max(1, min(int(anzahl or 60), 500))
    except (TypeError, ValueError):
        n = 60
    with _sperre:
        M = sorted((m for m in _mails()["mails"] if not m.get("erledigt")), key=lambda m: -m["zeit"])
    W = [m for m in M if m.get("wichtig")]
    R = [m for m in M if not m.get("wichtig")]
    return dict(stand(), wichtig=[_ohne_text(m) for m in W[:n]], rest=[_ohne_text(m) for m in R[:n]], neu=sum(1 for m in M if not m.get("gelesen")),
                unbewertet=sum(1 for m in M if m.get("status") == "neu"), gesamt=len(M))


def lesen(nr):
    with _sperre:
        return dict(_finden(_mails(), nr))


def aendern(von, nr, b):
    """Gelesen, erledigt, wichtig ja/nein. Beim Besitzer wird „wichtig“ zur Regel für den Absender."""
    with _sperre:
        d = _mails()
        m = _finden(d, nr)
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
    return _ohne_text(m)


def offen(anzahl=10):
    """Für einen Agenten mit Erlaubnis: unbewertete Mails, die älteste zuerst, mit Text."""
    try:
        n = max(1, min(int(anzahl or 10), 30))
    except (TypeError, ValueError):
        n = 10
    with _sperre:
        M = sorted((m for m in _mails()["mails"] if m["status"] == "neu"), key=lambda m: m["zeit"])[:n]
    return {"mails": [dict({k: m[k] for k in ("nr", "konto", "zeit", "von", "von_name", "an", "betreff", "anhaenge", "alt")}, text=m["text"][:6000]) for m in M]}


def bewerten(von, nr, b):
    """Urteil eines Agenten. Die Regel des Besitzers für den Absender geht vor."""
    with _sperre:
        d = _mails()
        m = _finden(d, nr)
        regeln = _konf().get("regeln") or {}
        m.update({"status": "bewertet", "wichtig": bool(regeln[m["von"]]) if m["von"] in regeln else bool(b.get("wichtig")),
                  "grund": str(b.get("grund") or "")[:300], "kurz": str(b.get("kurz") or "")[:600], "bewertet_von": von})
        _mails_schreiben(d)
    return _ohne_text(m)
