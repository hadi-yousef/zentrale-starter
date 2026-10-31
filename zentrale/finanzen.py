"""Zentrale: Finanzen des Besitzers (Seite „Finanzen“). Ein Haushaltsbuch, in dem jeder Cent zählt, dazu Verträge
und Abos, Sparziele, Kontostände, offene Rechnungen und ein Berater, der auf Abos und teure Monate hinweist.

Privat und Firma sind getrennt. Zahlen kommen aus Kontoauszügen (CSV sofort, PDF und Bilder liest ein Agent und bucht sie
mit `buchungen-eintragen`) und von Hand (Seite oder Client, „35 € Tanken“).

Beträge sind immer ganze Cent (int). Buchungen: Einnahme +, Ausgabe −. Verträge und Ziele: Beträge immer positiv.

Gespeichert in DATEN/finanzen.json:
  buchungen: [{id, nr, bereich (privat|firma), datum JJJJ-MM-TT, betrag_cent, text, gegenpartei, kategorie, kategorie_quelle
               (auto|regel|hand|agent), quelle (csv|pdf|bild|bote|hand|agent), konto, import_id, eingang (nr|None), notiz,
               von, zeit, entfernt (zeit|None), abgeglichen (z. B. „csv“, wenn eine Hand-Buchung im Auszug wiederkam)}]
  vertraege: [{id, nr, bereich, name, betrag_cent, rhythmus (monat|quartal|jahr|woche), kategorie, beginn, kuendbar_bis,
               kuendigungsfrist, naechste_zahlung, testphase_bis, behalten, notiz, status (aktiv|gekuendigt), hinweis, gegenpartei,
               von, zeit, entfernt}]
  ziele:     [{id, nr, bereich, name, ziel_cent, stand_cent, bis, notiz, verlauf: [{zeit, stand_cent, von}], zeit, entfernt}]
  konten:    [{id, bereich, name, auch (weitere Namen desselben Kontos), stand_cent, datum, quelle, zeit}]
  regeln:    {gegenpartei-schlüssel: kategorie}  (merkt sich, wenn der Besitzer eine Kategorie ändert)
  tipps:     [{id, nr, bereich, text, art (agent), von, zeit, erledigt}]  dazu eingebaute Regeln (art „regel“), nicht gespeichert
  regel_erledigt: {tipp-id: zeit}, abo_ignoriert: ["bereich|schlüssel"]
  eingang:   [{nr, id, name, datei, art (csv|pdf|bild), bereich, konto, bytes, sha256, von, zeit, status (wartet|erledigt),
               erledigt, erledigt_von, ergebnis, buchungen, ablage}]
  rechnungen: [{id, nr, bereich, name, betrag_cent, faellig, rechnungsnr, gegenpartei, link, notiz, dateien [ablage-pfad],
               bei_lohn, status (offen|bezahlt), bezahlt, bezahlt_von, buchung (nr|None), von, zeit, entfernt}]
Dateien aus dem Eingang liegen in DATEN/finanzen-eingang/<nr>.<endung>. Ist finanzen.json unlesbar, wird nichts geschrieben.

Ablage: DATEN/finanzen (oder FINANZ_DIR) mit <Privat|Firma>/<Kontoauszüge|Belege|Rechnungen>/<Jahr>/, dazu Haushaltsbuch.csv
und Übersicht.md je Bereich, nach jeder Änderung neu geschrieben.
"""
import base64
import csv
import hashlib
import io
import json
import os
import re
import secrets
import statistics
import threading
import time
from datetime import date, timedelta
from pathlib import Path

import hub

DATEI = hub.STATE_DIR / "finanzen.json"
EINGANG = hub.STATE_DIR / "finanzen-eingang"
ORDNER = Path(os.environ.get("FINANZ_DIR") or hub.STATE_DIR / "finanzen")
B = hub.BESITZER
ABLAGE = {"auszug": "Kontoauszüge", "beleg": "Belege", "rechnung": "Rechnungen"}
DATEI_MAX = 10 * 1024 * 1024
BEREICHE = ("privat", "firma")
RHYTHMEN = {"monat": 1, "quartal": 3, "jahr": 12, "woche": None}
QUELLEN = ("csv", "pdf", "bild", "bote", "hand", "agent")
ID = re.compile(r"^[0-9a-f]{6}$")
_sperre = threading.Lock()

# Kategorien: Schlüssel, Emoji, Name. Reihenfolge = Anzeige in Auswahllisten.
KATEGORIEN = [
    ("wohnen", "🏠", "Wohnen"), ("lebensmittel", "🛒", "Lebensmittel"), ("werkzeug", "🔧", "Baumarkt und Werkzeug"),
    ("auto", "🚗", "Auto"), ("unterwegs", "🚆", "Öffis und Reisen"), ("abos", "📺", "Abos"), ("handy", "📱", "Handy und Internet"),
    ("essen", "🍽️", "Essen gehen"), ("einkaufen", "🛍️", "Einkaufen"), ("gesundheit", "💊", "Gesundheit"),
    ("versicherung", "🛡️", "Versicherungen"), ("freizeit", "🎟️", "Freizeit"), ("bildung", "🎓", "Bildung"),
    ("geschenke", "🎁", "Geschenke"), ("bargeld", "💵", "Bargeld"), ("gebuehren", "🧾", "Bankgebühren"),
    ("steuern", "🏛️", "Steuern und Abgaben"), ("firma", "💼", "Firma"), ("einnahmen", "💶", "Einnahmen"),
    ("sparen", "🏦", "Sparen"), ("umbuchung", "🔁", "Umbuchung (eigene Konten)"), ("sonstiges", "❓", "Sonstiges"),
]
KAT = {k: (e, n) for k, e, n in KATEGORIEN}
NICHT_AUSGABE = {"einnahmen", "sparen", "umbuchung"}

# Schlüsselwörter für die automatische Zuordnung (Händler in Österreich und Deutschland). „*“ am Ende = Wortanfang reicht.
# Reihenfolge zählt: die erste passende Kategorie gewinnt.
STICHWORTE = [
    ("sparen", "sparplan* sparen sparkonto bausparen bausparkasse* wüstenrot wuestenrot depot etf festgeld trade_republic flatex scalable bitpanda"),
    ("umbuchung", "umbuchung* übertrag uebertrag eigenübertrag eigenuebertrag top-up topup aufladung eigenes_konto"),
    ("versicherung", "versicherung* uniqa generali allianz grawe zürich zurich helvetia ergo hdi svs"),
    ("steuern", "finanzamt einkommensteuer umsatzsteuer lohnsteuer kammerumlage wko wirtschaftskammer gemeinde* steuer*"),
    ("gebuehren", "kontoführung* kontofuehrung* spesen entgelt kartengebühr* kartengebuehr* jahresgebühr* jahresgebuehr* sollzinsen kontopaket*"),
    ("bargeld", "bankomat geldautomat atm behebung* bargeld* cash"),
    ("wohnen", "miete mietzins betriebskosten nebenkosten stadtwerke* energie* strom* gas* fernwärme fernwaerme hausverwaltung rundfunk* ikea"),
    ("handy", "a1 magenta drei spusu yesss telekom vodafone o2 telefonica 1&1 congstar internet mobilfunk*"),
    ("abos", "netflix spotify disney* dazn sky apple.com/bill apple_music icloud google_one youtube* prime_video amazon_prime audible "
             "microsoft_365 dropbox playstation_plus xbox_game_pass nintendo_online"),
    ("auto", "omv bp shell jet eni avanti turmöl turmoel tankstelle* tanken diesel benzin asfinag vignette parken parkgarage* parkschein* öamtc oeamtc arbö arboe "
             "werkstatt* reifen* kfz wipark apcoa easypark handyparken"),
    ("unterwegs", "öbb oebb westbahn flixbus ryanair austrian_airlines wizz booking.com airbnb hotel* uber bolt taxi* lufthansa easyjet eurowings klimaticket"),
    ("lebensmittel", "billa spar eurospar interspar hofer lidl penny merkur nah&frisch adeg denn's metro aldi rewe edeka netto kaufland "
                     "bäckerei* baeckerei* fleischerei* metzger* lebensmittel*"),
    ("werkzeug", "hornbach obi bauhaus baumax lagerhaus hagebau toom globus_baumarkt baumarkt* werkzeug*"),
    ("essen", "mcdonald* burger_king kfc subway lieferando mjam foodora wolt restaurant* gasthaus* gasthof* café cafe* pizzeria* pizza* kebap* kebab* döner* doener* "
              "starbucks nordsee vapiano wirtshaus* heuriger imbiss* bistro* sushi* kaffee* mittagessen essen_gehen"),
    ("gesundheit", "apotheke* arzt ärztin* zahnarzt* ordination optiker* fielmann labor* physio* spital krankenhaus"),
    ("bildung", "wifi bfi udemy coursera fachbuch* universität* universitaet* kursbeitrag* prüfungsgebühr* pruefungsgebuehr*"),
    ("freizeit", "kino* cineplexx fitness* mcfit john_harris fitinn clever_fit steam eventim oeticket ticket* therme* museum* zoo bowling"),
    ("einkaufen", "amazon* amzn* mediamarkt media_markt saturn dm bipa müller mueller h&m zara zalando xxxlutz kika leiner thalia libro pagro ebay willhaben "
                  "aliexpress temu shein galaxus cyberport"),
]
EINNAHME_WORTE = "gehalt lohn bezug bezüge bezuege honorar familienbeihilfe ams arbeitslosengeld pension rückerstattung* rueckerstattung* erstattung* gutschrift zinsen*"
_STOP = set("gmbh ag kg co mbh se sa sarl s a r l ltd inc bv eu at de com www dankt danke sagt filiale the und".split())


def _muster(worte):
    """Schlüsselwörter → ein regulärer Ausdruck mit Wortgrenzen. „_“ verbindet mehrteilige Namen („wiener_linien“), „*“ = Wortanfang reicht."""
    alt = []
    for w in worte.split():
        stern = w.endswith("*")
        w = re.escape(w.rstrip("*")).replace("_", r"\s+")
        alt.append(w + (r"\w*" if stern else ""))
    return re.compile(r"(?<![\w])(?:" + "|".join(sorted(alt, key=len, reverse=True)) + r")(?![\w])", re.I)


_KAT_MUSTER = [(k, _muster(w)) for k, w in STICHWORTE]
_EIN_MUSTER = _muster(EINNAHME_WORTE)


# ---------- Hilfen ----------

def _lesen():
    try:
        d = json.loads(DATEI.read_text())
    except FileNotFoundError:
        d = {}
    except (OSError, ValueError):
        raise ValueError("Die Finanzen lassen sich gerade nicht lesen. Es wird nichts überschrieben.")
    for k, v in (("buchungen", []), ("vertraege", []), ("ziele", []), ("konten", []), ("regeln", {}), ("tipps", []),
                 ("regel_erledigt", {}), ("abo_ignoriert", []), ("eingang", []), ("rechnungen", [])):
        d.setdefault(k, v)
    return d


def _schreiben(d):
    DATEI.parent.mkdir(parents=True, exist_ok=True)
    tmp = DATEI.with_name(DATEI.name + ".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False))
    tmp.replace(DATEI)
    _export_spaeter()


def _text(v, n, pflicht=False, was="Text"):
    t = re.sub(r"[ \t]+", " ", str(v or "").replace("\r\n", "\n")).strip()[:n]
    if pflicht and not t:
        raise ValueError(f"{was} fehlt.")
    return t


def _bereich(v, standard="privat"):
    v = str(v or standard).strip().lower()
    if v not in BEREICHE:
        raise ValueError("Bereich muss privat oder firma sein.")
    return v


def _kat(v):
    v = str(v or "").strip().lower()
    if v in KAT:
        return v
    for k, e, n in KATEGORIEN:   # auch „Lebensmittel“ oder „🛒“ geht
        if v in (n.lower(), e) or (len(v) >= 4 and n.lower().startswith(v)):
            return k
    raise ValueError(f"Unbekannte Kategorie „{v}“. Möglich: {', '.join(KAT)}.")


def _nr(liste):
    return max([x.get("nr") or 0 for x in liste] + [0]) + 1


def _jetzt():
    return int(time.time())


def heute():
    return date.today()


def eur(cent, vorzeichen=False):
    """1234567 → „12.345,67 €“ (mit echtem Minus)."""
    c = int(cent or 0)
    s = f"{abs(c) // 100:,}".replace(",", ".") + f",{abs(c) % 100:02d} €"
    return ("−" if c < 0 else "+" if vorzeichen and c > 0 else "") + s


def betrag_cent(v):
    """Euro-Text oder Zahl → Cent. Versteht 1.234,56 · 1234.56 · 1,234.56 · -12,30 · 12,30- · +2.950 · € 35 · 35 EUR. None = keine Zahl."""
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v * 100
    if isinstance(v, float):
        return int(round(v * 100))
    s = str(v).strip().replace(" ", "").replace(" ", "").replace(" ", "").replace("'", "")
    s = re.sub(r"(?i)(eur(o)?|€)", "", s)
    if not s:
        return None
    neg = False
    if s[0] in "+-−–":
        neg = s[0] != "+"
        s = s[1:]
    if s and s[-1] in "+-−–":
        neg = s[-1] != "+"
        s = s[:-1]
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1]
    if not re.fullmatch(r"[\d.,]+", s) or not re.search(r"\d", s):
        return None
    if "," in s and "." in s:
        dez = "," if s.rfind(",") > s.rfind(".") else "."
    elif "," in s:
        dez = "," if re.search(r",\d{1,2}$", s) else None
    elif "." in s:
        dez = "." if re.search(r"\.\d{1,2}$", s) and s.count(".") == 1 else None
    else:
        dez = None
    if dez:
        ganz, _, rest = s.rpartition(dez)
        ganz = re.sub(r"[.,]", "", ganz) or "0"
        rest = (rest + "00")[:2]
    else:
        ganz, rest = re.sub(r"[.,]", "", s), "00"
    if not ganz.isdigit() or len(ganz) > 12:
        return None
    c = int(ganz) * 100 + int(rest)
    return -c if neg else c


def _cent_feld(b, name, pflicht=False, positiv=False):
    """Aus b[name_cent] (int) oder b[name] (Euro-Text) Cent machen."""
    if b.get(name + "_cent") not in (None, ""):
        try:
            c = int(b[name + "_cent"])
        except (TypeError, ValueError):
            raise ValueError(f"{name}_cent muss eine ganze Zahl sein.")
    elif b.get(name) not in (None, ""):
        c = betrag_cent(b[name])
        if c is None:
            raise ValueError(f"„{b[name]}“ ist kein Betrag.")
    else:
        if pflicht:
            raise ValueError(f"Betrag ({name}) fehlt.")
        return None
    if abs(c) > 10 ** 12:
        raise ValueError("Der Betrag ist zu groß.")
    return abs(c) if positiv else c


_MONATE = {"jän": 1, "jan": 1, "feb": 2, "mär": 3, "mar": 3, "apr": 4, "mai": 5, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "okt": 10, "oct": 10, "nov": 11, "dez": 12, "dec": 12}


def datum_text(v, standardjahr=None):
    """Datum aus Bankexporten → „JJJJ-MM-TT“ oder None. DD.MM.JJJJ, DD.MM.JJ, JJJJ-MM-TT (auch mit Uhrzeit), DD/MM/JJJJ, JJJJ/MM/TT, DD.MM."""
    s = str(v or "").strip().strip('"')
    if not s:
        return None
    m = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[ T].*)?$", s)
    if m:
        j, mo, t = int(m[1]), int(m[2]), int(m[3])
    else:
        m = re.match(r"^(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})(?:[ ,T].*)?$", s)
        if m:
            t, mo, j = int(m[1]), int(m[2]), int(m[3])
            j += 2000 if j < 100 else 0
        else:
            m = re.match(r"^(\d{1,2})\.?\s*([a-zäA-ZÄ]{3})[a-zäA-ZÄ]*\.?\s*(\d{4})$", s)
            if m and m[2].lower()[:3] in _MONATE:
                t, mo, j = int(m[1]), _MONATE[m[2].lower()[:3]], int(m[3])
            else:
                m = re.match(r"^(\d{1,2})\.(\d{1,2})\.?$", s)
                if not m or not standardjahr:
                    return None
                t, mo, j = int(m[1]), int(m[2]), standardjahr
    try:
        d = date(j, mo, t)
    except ValueError:
        return None
    return d.isoformat() if 1990 <= d.year <= 2100 else None


def _datum_feld(v, pflicht=True):
    d = datum_text(v)
    if not d:
        if not pflicht and not str(v or "").strip():
            return ""
        raise ValueError(f"„{v}“ ist kein Datum (JJJJ-MM-TT).")
    return d


def _monat(v=None):
    v = str(v or "").strip()
    if not v:
        return heute().strftime("%Y-%m")
    if not re.fullmatch(r"\d{4}-\d{2}", v) or not 1 <= int(v[5:]) <= 12:
        raise ValueError("Monat bitte als JJJJ-MM.")
    return v


def _monat_plus(m, n):
    j, mo = int(m[:4]), int(m[5:7]) - 1 + n
    return f"{j + mo // 12:04d}-{mo % 12 + 1:02d}"


def _monat_name(m, jahr=True):
    n = ["Jänner", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"][int(m[5:7]) - 1]
    return f"{n} {m[:4]}" if jahr else n


def schluessel(s):
    """Gegenpartei → Vergleichsschlüssel: klein, ohne Rechtsform und Ziffern, höchstens zwei Wörter („NETFLIX.COM“ → „netflix“)."""
    s = str(s or "").lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    w = [x for x in re.split(r"[^a-z0-9&+]+", s) if x and x not in _STOP and not x.isdigit()]
    w = w[:1] + [x for x in w[1:] if not re.search(r"\d", x)]   # „A1 Telekom“ bleibt, „Spotify P2A3B“ wird „spotify“
    return " ".join(w[:2])


_PRAEFIX = re.compile(r"(?i)\b(bezahlung|zahlung|kartenzahlung|karte|maestro|debitkarte|kreditkarte|pos|sepa|lastschrift|überweisung|ueberweisung|dauerauftrag|"
                      r"abbuchung|einzug|e-comm|ecom|apple pay|google pay|debit|mc/\d+|vd/\d+|k\d|online|einkauf|kauf|bei|an|von)\b[:.]?")


def gegenpartei_aus_text(t):
    """Aus einem Buchungstext wie „Bezahlung Karte MC/000002123 BILLA DANKT 4321\\WIEN“ die Gegenpartei („Billa“) machen."""
    s = _PRAEFIX.sub(" ", str(t or ""))
    s = re.sub(r"(?i)\b(dankt|danke|sagt)\b", " ", s)
    out = []
    for w in s.split():
        if "\\" in w:
            w = w.split("\\")[0]
            if w and not re.search(r"\d", w):
                out.append(w)
            break
        if re.search(r"\d", w) and out:
            break
        if re.fullmatch(r"[\d.,:/-]+", w):
            continue
        out.append(w)
        if len(out) >= 3:
            break
    g = " ".join(out).strip(" ,;-*")[:60]
    return g.title() if g.isupper() and len(g) > 4 else g


def _schoen(g):
    g = re.sub(r"(?i)\s+(sagt\s+danke|dankt|danke)\b.*$", "", _text(g, 80))   # „BILLA DANKT“ → „Billa“
    return g.title() if g.isupper() and len(g) > 4 else g


def kategorie_raten(text, gegenpartei, betrag, regeln=None):
    """→ (kategorie, quelle). Erst die gelernten Regeln (gegenpartei → kategorie), dann Schlüsselwörter. Einnahmen ohne Treffer → einnahmen."""
    regeln = regeln or {}
    k = schluessel(gegenpartei or gegenpartei_aus_text(text))
    if k and k in regeln:
        return regeln[k], "regel"
    such = re.sub(r"(?i)\b(apple|google)\s*pay\b", " ", f"{gegenpartei or ''} {text or ''}")   # „Google Pay BILLA“ ist kein Abo
    if betrag > 0 and _EIN_MUSTER.search(such):
        return "einnahmen", "auto"
    for kat, m in _KAT_MUSTER:
        if m.search(such):
            return kat, "auto"
    return ("einnahmen" if betrag > 0 else "sonstiges"), "auto"


def _import_id(bereich, datum, betrag, text, konto):
    t = re.sub(r"\s+", " ", str(text or "").lower()).strip()
    roh = f"{bereich}|{datum}|{betrag}|{t}|{str(konto or '').lower().strip()}"
    return hashlib.sha1(roh.encode()).hexdigest()[:16]


def _sichtbar(B, bereich=None):
    return [b for b in B if not b.get("entfernt") and (bereich is None or b["bereich"] == bereich)]


def _finden(liste, wid, was):
    wid = str(wid or "").strip().lstrip("#")
    if wid.isdigit() and len(wid) < 6:
        x = next((x for x in liste if x.get("nr") == int(wid)), None)
    else:
        x = next((x for x in liste if x.get("id") == wid), None) if ID.match(wid) else None
    if not x or x.get("entfernt"):
        raise ValueError(f"{was} gibt es nicht.")
    return x


def kategorien():
    return [{"key": k, "emoji": e, "name": n} for k, e, n in KATEGORIEN]


# ---------- CSV-Import ----------

def _dekodieren(roh):
    if roh[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return roh.decode("utf-16"), "utf-16"
    for k in ("utf-8-sig", "cp1252"):
        try:
            return roh.decode(k), k
        except UnicodeDecodeError:
            pass
    return roh.decode("latin-1"), "latin-1"


def _kopf(h):
    h = str(h or "").lower().strip().strip('"﻿').replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    return re.sub(r"\s+", " ", h)


# Spalten per Kopfzeile erraten: Liste von (Rolle, genaue Namen, Wortteile, verbotene Wortteile)
_ROLLEN = [
    ("datum", ["buchungsdatum", "booking date", "buchungstag", "datum", "date", "completed date", "transaktionsdatum", "started date",
               "valutadatum", "valuta", "value date", "wertstellung", "buchung"], ["buchungsdatum", "datum", "date"], ["valuta", "value", "zeitstempel"]),
    ("betrag", ["betrag", "amount (eur)", "amount", "betrag (eur)", "umsatz", "betrag in eur", "umsatz in eur", "betrag eur", "wert", "summe", "eur"],
     ["betrag", "amount", "umsatz"], ["foreign", "fremd", "original", "fee", "gebuehr", "waehrung", "currency"]),
    ("soll", ["soll", "debit", "belastung", "abgang", "ausgang"], [], []),
    ("haben", ["haben", "credit", "gutschrift", "zugang", "eingang"], [], []),
    ("sh", ["soll/haben", "s/h", "soll-haben", "debit/credit", "cr/dr", "s/h-kennzeichen"], [], []),
    ("gegenpartei", ["partnername", "partner name", "empfaenger", "empfaengername", "auftraggeber", "auftraggeber/empfaenger", "empfaenger/auftraggeber",
                     "zahlungsempfaenger", "beguenstigter/zahlungspflichtiger", "name zahlungsbeteiligter", "payee", "counterparty", "merchant", "partner", "name",
                     "auftraggebername", "gegenkonto name", "zahlungspflichtiger"],
     ["partner", "empfaenger", "auftraggeber", "beguenstigt", "payee", "zahlungsbeteiligter", "counterparty", "merchant"],
     ["iban", "konto", "account", "bic", "nummer", "bank", "blz", "number", "swift", "adresse", "referenz"]),
    ("saldo", ["saldo", "balance", "kontostand", "saldo nach buchung", "neuer saldo"], ["saldo", "balance", "kontostand"], []),
    ("waehrung", ["waehrung", "currency", "wahrung"], [], []),
    ("status", ["state", "status"], [], []),
    ("gebuehr", ["fee", "gebuehr", "gebuehren"], [], []),
]
_TEXTE = ["verwendungszweck", "buchungstext", "description", "payment reference", "zahlungsreferenz", "beschreibung", "umsatztext", "text",
          "buchungsinformation", "buchungsdetails", "reference", "transaktionstext", "details", "zweck", "buchungs-informationen"]
_ARTEN = ["type", "transaction type", "art", "buchungsart", "umsatzart"]   # nur als Text, wenn sonst nichts dasteht


def _spalten(kopf):
    K = [_kopf(h) for h in kopf]
    S, belegt = {}, set()
    for rolle, genau, teile, verboten in _ROLLEN:
        i = next((j for g in genau for j, h in enumerate(K) if h == g and j not in belegt), None)
        if i is None and teile:
            i = next((j for j, h in enumerate(K) if j not in belegt and any(t in h for t in teile) and not any(v in h for v in verboten)), None)
        if i is not None:
            S[rolle] = i
            belegt.add(i)
    S["texte"] = [j for t in _TEXTE for j, h in enumerate(K) if h == t and j not in belegt]
    S["texte"] = list(dict.fromkeys(S["texte"]))
    S["arten"] = [j for t in _ARTEN for j, h in enumerate(K) if h == t and j not in belegt]
    return S


def _bank(kopf, name):
    K, n = {_kopf(h) for h in kopf}, str(name or "").lower()
    if {"started date", "completed date"} <= K:
        return "Revolut"
    if "amount (eur)" in K or ("booking date" in K and "partner name" in K):
        return "N26"
    for w, b in (("george", "George"), ("erste", "George"), ("sparkasse", "George"), ("bank austria", "Bank Austria"), ("bankaustria", "Bank Austria"), ("bank_austria", "Bank Austria"), ("n26", "N26"), ("revolut", "Revolut"),
                 ("easybank", "easybank"), ("bawag", "BAWAG"), ("dkb", "DKB"), ("ing", "ING")):
        if w in n:
            return b
    if "partnername" in K or "partner iban" in K:
        return "George"
    return "Konto"


def csv_lesen(roh, name=""):
    """Bankexport (CSV) → (zeilen, info). zeilen: [{datum, betrag_cent, text, gegenpartei, saldo_cent, waehrung}].
    Kodierung utf-8/cp1252/utf-16, Trennzeichen ; , Tab |, Kopfzeile irgendwo in den ersten 20 Zeilen oder ganz ohne."""
    text, kod = _dekodieren(roh)
    zeilen = [z for z in text.splitlines() if z.strip()]
    if not zeilen:
        raise ValueError("Die Datei ist leer.")
    best = None
    for t in ";,\t|":
        R = list(csv.reader(zeilen[:40], delimiter=t))
        n = [len(r) for r in R if len(r) > 1]
        if not n:
            continue
        haeufig = max(set(n), key=n.count)
        wert = (n.count(haeufig), haeufig)
        if best is None or wert > best[0]:
            best = (wert, t)
    if not best:
        raise ValueError("In der Datei sind keine Spalten zu erkennen. Ist das wirklich eine CSV-Datei?")
    trenner = best[1]
    R = list(csv.reader(io.StringIO("\n".join(zeilen)), delimiter=trenner))
    kopf_i, S = None, None
    for i, r in enumerate(R[:20]):
        s = _spalten(r)
        if "datum" in s and ("betrag" in s or ("soll" in s and "haben" in s)) and not datum_text(r[s["datum"]] if s["datum"] < len(r) else ""):
            kopf_i, S = i, s
            break
    if S is None:
        S = _ohne_kopf(R)
        kopf, daten = [], R
    else:
        kopf, daten = R[kopf_i], R[kopf_i + 1:]
    aus, ueber = [], 0
    for r in daten:
        g = lambda rolle: r[S[rolle]].strip() if rolle in S and S[rolle] < len(r) else ""
        d = datum_text(g("datum"))
        if "betrag" in S:
            c = betrag_cent(g("betrag"))
        else:
            so, ha = betrag_cent(g("soll")), betrag_cent(g("haben"))
            c = None if so is None and ha is None else (ha or 0) - abs(so or 0)
        if not d or c is None:
            ueber += 1
            continue
        if g("sh").upper()[:1] in ("S", "D") and c > 0:
            c = -c
        st = g("status").upper()
        if st and any(w in st for w in ("REVERTED", "DECLINED", "FAILED", "STORNIERT", "ABGELEHNT")):
            ueber += 1
            continue
        geb = betrag_cent(g("gebuehr")) if "gebuehr" in S else None
        if geb:
            c -= abs(geb)
        teile = [r[j].strip() for j in S["texte"] if j < len(r) and r[j].strip()]
        txt = " · ".join(dict.fromkeys(teile))[:300]
        gp = _schoen(g("gegenpartei")) or gegenpartei_aus_text(teile[0] if teile else "")
        art = next((r[j].strip() for j in S.get("arten", []) if j < len(r) and r[j].strip()), "")
        aus.append({"datum": d, "betrag_cent": c, "text": txt or gp or art or "(ohne Text)", "gegenpartei": gp,
                    "saldo_cent": betrag_cent(g("saldo")) if "saldo" in S else None, "waehrung": g("waehrung").upper()})
    if not aus:
        raise ValueError("Keine Buchungen gefunden. Es fehlt eine Spalte mit Datum oder Betrag.")
    return aus, {"bank": _bank(kopf, name), "trennzeichen": trenner, "kodierung": kod, "kopfzeile": bool(kopf), "uebersprungen": ueber}


def _ohne_kopf(R):
    """Datei ohne Kopfzeile (manche Banken exportieren so): Spalten am Inhalt erkennen."""
    R = [r for r in R if len(r) > 1][:60]
    if not R:
        raise ValueError("In der Datei sind keine Spalten zu erkennen.")
    n = max(len(r) for r in R)
    anteil = lambda f, j: sum(1 for r in R if j < len(r) and f(r[j])) / len(R)
    D = [j for j in range(n) if anteil(datum_text, j) >= .8]
    if not D:
        raise ValueError("Keine Spalte mit einem Datum gefunden.")
    B = [j for j in range(n) if j not in D and anteil(lambda v: betrag_cent(v) is not None and re.search(r"[.,]\d{2}\s*-?$|^-", v.strip()), j) >= .8]
    if not B:
        raise ValueError("Keine Spalte mit einem Betrag gefunden.")
    rest = [j for j in range(n) if j not in D and j not in B]
    laenge = lambda j: sum(len(r[j]) for r in R if j < len(r)) / len(R)
    T = sorted([j for j in rest if anteil(lambda v: bool(re.search(r"[A-Za-zÄÖÜäöü]{3}", v)), j) >= .5], key=laenge, reverse=True)
    return {"datum": D[0], "betrag": B[0], "texte": T[:1]}


# ---------- Buchungen ----------

def _buchung_bauen(d, von, b, quelle, bereich=None):
    """Prüft eine Buchung und gibt sie fertig zurück (noch nicht gespeichert)."""
    betrag = _cent_feld(b, "betrag", pflicht=True)
    if betrag == 0:
        raise ValueError("Der Betrag ist 0.")
    text = _text(b.get("text"), 300) or _text(b.get("gegenpartei"), 80)
    if not text:
        raise ValueError("Text fehlt (wofür war das Geld?).")
    gp = _schoen(b.get("gegenpartei")) or gegenpartei_aus_text(text)
    x = {"id": hub.neue_id(d["buchungen"]), "nr": 0, "bereich": _bereich(b.get("bereich") or bereich), "datum": _datum_feld(b.get("datum") or heute().isoformat()),
         "betrag_cent": betrag, "text": text, "gegenpartei": gp, "kategorie": "", "kategorie_quelle": "auto",
         "quelle": quelle, "konto": _text(b.get("konto"), 60), "import_id": "", "eingang": None, "notiz": _text(b.get("notiz"), 1000),
         "von": von, "zeit": _jetzt(), "entfernt": None}
    if b.get("kategorie"):
        x["kategorie"], x["kategorie_quelle"] = _kat(b["kategorie"]), ("hand" if von == B else "agent")
    else:
        x["kategorie"], x["kategorie_quelle"] = kategorie_raten(text, gp, betrag, d["regeln"])
    return x


def _gleicher_vorgang(b, x):
    """Passt eine Hand-Buchung b zur Buchung x aus dem Auszug? Konto, Gegenpartei und Kategorie dürfen sich nicht widersprechen."""
    if b.get("konto") and x.get("konto") and schluessel(b["konto"]) != schluessel(x["konto"]):
        return False
    gb, gx = schluessel(b.get("gegenpartei")), schluessel(x.get("gegenpartei"))
    # Die Gegenpartei wird oft aus dem Satz abgeleitet („35 € Tanken“ → „Tanken“). Nur eine echt angegebene zählt.
    echt = gb and gb.split()[0] not in schluessel(b.get("text"))
    if echt and gx and gb.split()[0] not in gx and gx.split()[0] not in gb:
        return False
    kb, kx = b.get("kategorie"), x.get("kategorie")
    if kb and kx and kb != kx and "sonstiges" not in (kb, kx):
        return False
    return True


def _abgleichen(d, x):
    """Kam eine Hand-Buchung jetzt im Kontoauszug? Dann zusammenführen statt doppelt zählen (gleicher Betrag, ±3 Tage)."""
    tag = date.fromisoformat(x["datum"])
    nahe = [b for b in _sichtbar(d["buchungen"], x["bereich"]) if b["quelle"] in ("bote", "hand") and not b.get("import_id") and b["betrag_cent"] == x["betrag_cent"]
            and abs((date.fromisoformat(b["datum"]) - tag).days) <= 3]
    kand = [b for b in nahe if _gleicher_vorgang(b, x)]
    # Nur zusammenführen, wenn genau eine Buchung passt (Prüfung 31.10.2026, F-01): Gleicher Betrag allein heißt nicht
    # gleicher Einkauf (20 € Essen bar und 20 € Tanken mit Karte). Ist es unsicher, gibt es zwei Buchungen mit Hinweis,
    # damit der Besitzer eine echte Doppelbuchung sieht und selbst entfernen kann.
    if len(kand) != 1:
        if nahe:
            x["notiz"] = (x["notiz"] + " " if x["notiz"] else "") + \
                "Vielleicht dieselbe wie Buchung Nr. " + ", ".join(str(b["nr"]) for b in nahe[:3]) + " (gleicher Betrag). Bitte prüfen."
        return None
    b = kand[0]
    b["notiz"] = b["notiz"] or f"Eingetragen als „{b['text']}“"
    for k in ("datum", "text", "konto", "import_id", "eingang"):
        if x.get(k):
            b[k] = x[k]
    b["gegenpartei"] = b["gegenpartei"] or x["gegenpartei"]
    b["abgeglichen"] = x["quelle"]
    return b


def _einfuegen(d, von, roh, quelle, bereich, konto="", eingang=None):
    """Mehrere Buchungen eintragen, Dubletten erkennen (gleiches Datum, Betrag, Text, Konto). → {neu, doppelt, zusammengefuehrt, fehler, buchungen}"""
    if len(d["buchungen"]) + len(roh) > 100000:
        raise ValueError("Zu viele Buchungen gespeichert.")
    bekannt = {b["import_id"] for b in d["buchungen"] if b.get("import_id")}
    zaehler, erg = {}, {"neu": 0, "doppelt": 0, "zusammengefuehrt": 0, "fehler": [], "buchungen": []}
    nr = _nr(d["buchungen"])
    for i, r in enumerate(roh):
        try:
            r = dict(r)
            r.setdefault("konto", konto)
            x = _buchung_bauen(d, von, r, quelle, bereich)
        except (ValueError, TypeError, AttributeError) as e:
            erg["fehler"].append(f"Zeile {i + 1}: {e}")
            continue
        basis = _import_id(x["bereich"], x["datum"], x["betrag_cent"], x["text"], x["konto"])
        zaehler[basis] = zaehler.get(basis, 0) + 1   # zweimal derselbe Einkauf am selben Tag zählt zweimal
        x["import_id"] = basis + (f"#{zaehler[basis]}" if zaehler[basis] > 1 else "")
        x["eingang"] = eingang
        if r.get("waehrung") and str(r["waehrung"]).strip().upper() not in ("EUR", "EURO", "€"):
            # Prüfung 31.10.2026, F-04: Fremdwährung nicht als Euro zählen. Nicht übernehmen, sondern melden.
            erg["fehler"].append(f"Zeile {i + 1}: {r['waehrung']} {eur(x['betrag_cent'])[:-2].strip()} ({x['text'][:40]}) nicht übernommen: "
                                 "Fremdwährung. Bitte in Euro eintragen (Betrag laut Kontoauszug).")
            continue
        if x["import_id"] in bekannt:
            erg["doppelt"] += 1
            continue
        alt = _abgleichen(d, x)
        if alt:
            erg["zusammengefuehrt"] += 1
            bekannt.add(x["import_id"])
            erg["buchungen"].append(alt)
            continue
        x["nr"], nr = nr, nr + 1
        d["buchungen"].append(x)
        bekannt.add(x["import_id"])
        erg["neu"] += 1
        erg["buchungen"].append(x)
    return erg


def buchung_neu(von, b):
    """Eine Buchung von Hand oder von einem Agenten."""
    quelle = b.get("quelle") or ("hand" if von == B else "agent")
    if quelle not in QUELLEN:
        raise ValueError(f"Quelle muss eine von {', '.join(QUELLEN)} sein.")
    with _sperre:
        d = _lesen()
        if len(d["buchungen"]) >= 100000:
            raise ValueError("Zu viele Buchungen gespeichert.")
        x = _buchung_bauen(d, von, b, quelle)
        x["nr"] = _nr(d["buchungen"])
        d["buchungen"].append(x)
        meldung = _nach_buchungen(d, [x])
        _schreiben(d)
    _besitzer_melden(meldung)
    return _zeigen(x)


def buchungen_menge(von, b):
    """Viele Buchungen auf einmal (Agent hat einen PDF-Auszug oder ein Bild gelesen). b: {buchungen: [...], eingang: nr, quelle: pdf|bild,
    bereich, konto, kontostand: {stand_cent|stand, datum, konto}, erledigt: true}. Der Eingang wird danach als erledigt markiert."""
    roh = b.get("buchungen")
    if not isinstance(roh, list) or not roh:
        raise ValueError("„buchungen“ muss eine Liste sein.")
    if len(roh) > 5000:
        raise ValueError("Höchstens 5000 Buchungen auf einmal.")
    with _sperre:
        d = _lesen()
        e = _eingang_finden(d, b["eingang"]) if b.get("eingang") not in (None, "") else None
        quelle = b.get("quelle") or (("bild" if e["art"] == "bild" else "pdf") if e else "agent")
        if quelle not in QUELLEN:
            raise ValueError(f"Quelle muss eine von {', '.join(QUELLEN)} sein.")
        bereich = _bereich(b.get("bereich") or (e["bereich"] if e else "privat"))
        konto = _text(b.get("konto") or (e or {}).get("konto"), 60)
        erg = _einfuegen(d, von, roh, quelle, bereich, konto, e["nr"] if e else None)
        meldung = _nach_buchungen(d, erg["buchungen"])
        if b.get("kontostand"):
            k = dict(b["kontostand"])
            _konto_setzen(d, von, {"bereich": bereich, "name": k.get("konto") or konto or "Konto", "stand_cent": k.get("stand_cent"), "stand": k.get("stand"),
                                   "datum": k.get("datum")}, "auszug")
        if e and b.get("erledigt", True):
            e.update(status="erledigt", erledigt=_jetzt(), erledigt_von=von, buchungen=(e.get("buchungen") or 0) + erg["neu"] + erg["zusammengefuehrt"],
                     ergebnis=_ergebnis_text(erg))
        _schreiben(d)
    _besitzer_melden(meldung)
    erg["buchungen"] = [_zeigen(x) for x in erg["buchungen"]]
    return erg


def buchung_aendern(von, bid, b):
    """Kategorie, Notiz, Bereich, Text, Datum, Betrag ändern oder entfernen (nur Markierung). Ändert der Besitzer die Kategorie,
    merkt sich die Zentrale das für diese Gegenpartei und ordnet ihre anderen (automatisch zugeordneten) Buchungen gleich zu."""
    with _sperre:
        d = _lesen()
        x = _finden(d["buchungen"], bid, "Diese Buchung")
        mit = 0
        if b.get("entfernen"):
            x["entfernt"] = _jetzt()
            x["entfernt_von"] = von
        if "bereich" in b:
            x["bereich"] = _bereich(b["bereich"])
        if "notiz" in b:
            x["notiz"] = _text(b["notiz"], 1000)
        if "text" in b:
            x["text"] = _text(b["text"], 300, True)
        if "gegenpartei" in b:
            x["gegenpartei"] = _schoen(b["gegenpartei"])
        if "datum" in b:
            x["datum"] = _datum_feld(b["datum"])
        if "konto" in b:
            x["konto"] = _text(b["konto"], 60)
        if b.get("betrag_cent") not in (None, "") or b.get("betrag") not in (None, ""):
            c = _cent_feld(b, "betrag", pflicht=True)
            if c == 0:
                raise ValueError("Der Betrag ist 0.")
            x["betrag_cent"] = c
        if b.get("kategorie"):
            x["kategorie"], x["kategorie_quelle"] = _kat(b["kategorie"]), ("hand" if von == B else "agent")
            k = schluessel(x["gegenpartei"] or gegenpartei_aus_text(x["text"]))
            if k and b.get("merken", von == B):   # Regel lernen: beim Besitzer immer, bei Agenten nur mit merken=true
                d["regeln"][k] = x["kategorie"]
                for y in d["buchungen"]:
                    if y is not x and y["kategorie_quelle"] in ("auto", "regel") and schluessel(y["gegenpartei"] or gegenpartei_aus_text(y["text"])) == k \
                            and y["kategorie"] != x["kategorie"]:
                        y["kategorie"], y["kategorie_quelle"] = x["kategorie"], "regel"
                        mit += 1
        _schreiben(d)
    return dict(_zeigen(x), mit_geaendert=mit)


def _zeigen(x):
    e, n = KAT.get(x["kategorie"], KAT["sonstiges"])
    return dict(x, emoji=e, kategorie_name=n)


def buchungen(bereich=None, monat=None, kategorie=None, q=None, anzahl=500):
    with _sperre:
        d = _lesen()
    B = _sichtbar(d["buchungen"], _bereich(bereich) if bereich else None)
    if monat:
        B = [b for b in B if b["datum"].startswith(_monat(monat))]
    if kategorie:
        k = _kat(kategorie)
        B = [b for b in B if b["kategorie"] == k]
    if q:
        w = str(q).lower().split()
        B = [b for b in B if all(x in f"{b['text']} {b['gegenpartei']} {b['notiz']} {b['konto']}".lower() for x in w)]
    B.sort(key=lambda b: (b["datum"], b["nr"]), reverse=True)
    return {"buchungen": [_zeigen(b) for b in B[:max(1, min(int(anzahl or 500), 5000))]], "anzahl": len(B)}


# ---------- Ein Satz wie „35 € Tanken“ ----------

_EIN_SATZ = re.compile(r"(?i)\b(lohn|gehalt|bekommen|erhalten|einnahme\w*|eingang|gutschrift|honorar|verkauft|zurückbekommen|rückerstattung|überwiesen bekommen|bezahlt bekommen)\b")
_ZAHL = r"(?<![A-Za-zÄÖÜäöü\d.,])(?:[+\-−]\s*)?(?:\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?)(?![\d])"


def satz_verstehen(text, bereich=None):
    """„35 € Tanken“, „Tanken 35,50“, „+1800 Lohn“, „gestern 12 Euro Pizza“, „Firma: 120 € Hornbach“ → Vorschlag (bucht nichts)."""
    s = _text(text, 300, True, "Satz")
    t = heute()
    datum = None
    for w, n in (("vorgestern", 2), ("gestern", 1), ("heute", 0)):
        if re.search(rf"(?i)\b{w}\b", s):
            datum, s = (t - timedelta(days=n)).isoformat(), re.sub(rf"(?i)\b{w}\b", " ", s)
            break
    m = re.search(r"\b(?:am\s+)?(\d{1,2}\.\d{1,2}\.(?:\d{2,4})?)", s)
    if m and not datum:
        datum = datum_text(m[1], t.year)
        if datum and datum > t.isoformat() and not re.search(r"\.\d{2,4}$", m[1]):
            datum = datum_text(m[1], t.year - 1)
        if datum:
            s = s.replace(m[0], " ")
    bm = re.search(r"(?i)^\s*(privat|firma)\s*[:,-]?\s*|\s*[(,-]?\s*\b(privat|firma)\b\s*\)?\s*$", s)
    if bm:
        bereich = (bm[1] or bm[2]).lower()   # „Firma: …“ im Satz gewinnt über die gerade offene Ansicht
        s = s[:bm.start()] + " " + s[bm.end():]
    kandidaten = []
    for m in re.finditer(_ZAHL, s):
        vor, nach = s[max(0, m.start() - 6):m.start()].lower(), s[m.end():m.end() + 6].lower()
        waehr = bool(re.search(r"(€|eur|euro)\s*$", vor) or re.match(r"\s*(€|eur|euro)", nach))
        kandidaten.append((waehr, m))
    if not kandidaten:
        raise ValueError("Im Satz steht kein Betrag. Beispiel: „35 € Tanken“.")
    waehr, m = next((k for k in kandidaten if k[0]), kandidaten[0] if len(kandidaten) == 1 else (None, None))
    if m is None:
        raise ValueError("Mehrere Zahlen im Satz. Schreib den Betrag mit €, z. B. „35 € Tanken“.")
    roh = m[0].replace(" ", "")
    c = betrag_cent(roh)
    if not c:
        raise ValueError("Der Betrag ist 0 oder nicht lesbar.")
    rest = (s[:m.start()] + " " + s[m.end():])
    rest = re.sub(r"(?i)(€|\beuro?\b|\beur\b)", " ", rest)
    rest = re.sub(r"(?i)^\s*(für|fuer|ausgegeben|bezahlt|gezahlt)\b|\b(ausgegeben|bezahlt|gezahlt)\s*$", " ", rest.strip())
    rest = re.sub(r"\s+", " ", rest).strip(" ,.:;-")
    einnahme = roh.startswith("+") or bool(_EIN_SATZ.search(rest))
    if not roh[0] in "+-−":
        c = abs(c) if einnahme else -abs(c)
    text = rest[:1].upper() + rest[1:] if rest else ("Einnahme" if c > 0 else "Ausgabe")
    gp = gegenpartei_aus_text(text)
    with _sperre:
        regeln = _lesen()["regeln"]
    k, kq = kategorie_raten(text, gp, c, regeln)
    return {"betrag_cent": c, "text": text, "datum": datum or t.isoformat(), "bereich": _bereich(bereich), "kategorie": k, "kategorie_quelle": kq,
            "emoji": KAT[k][0], "kategorie_name": KAT[k][1], "satz": _text(text, 300)}


def satz_buchen(von, b):
    v = satz_verstehen(b.get("text"), b.get("bereich"))
    roh = {"betrag_cent": v["betrag_cent"], "text": v["text"], "datum": b.get("datum") or v["datum"], "bereich": v["bereich"],
           "kategorie": b.get("kategorie") or None, "konto": b.get("konto") or "", "notiz": b.get("notiz") or ""}
    x = buchung_neu(von, dict(roh, quelle=b.get("quelle") or ("agent" if von != B else "hand")))
    return x


# ---------- Eingang: Dateien hochladen (CSV sofort, PDF und Bilder für den Agenten) ----------

def _art(roh, name):
    n = str(name or "").lower()
    if roh[:5] == b"%PDF-":
        return "pdf", "pdf"
    if roh[:8] == b"\x89PNG\r\n\x1a\n":
        return "bild", "png"
    if roh[:3] == b"\xff\xd8\xff":
        return "bild", "jpg"
    if roh[:4] == b"RIFF" and roh[8:12] == b"WEBP":
        return "bild", "webp"
    if roh[4:12] in (b"ftypheic", b"ftypheix", b"ftypmif1", b"ftyphevc"):
        return "bild", "heic"
    if n.endswith((".csv", ".txt", ".tsv")) or (b"\x00" not in roh[:2000] or roh[:2] in (b"\xff\xfe", b"\xfe\xff")):
        return "csv", "csv"
    raise ValueError("Nur CSV, PDF oder Bilder (PNG, JPEG, WebP, HEIC).")


def _eingang_finden(d, nr):
    nr = str(nr or "").strip().lstrip("#")
    e = next((x for x in d["eingang"] if str(x["nr"]) == nr or x.get("id") == nr), None)
    if not e:
        raise ValueError("Diesen Eingang gibt es nicht.")
    return e


def _ergebnis_text(erg):
    t = f"{erg['neu']} neu, {erg['doppelt']} doppelt"
    if erg.get("zusammengefuehrt"):
        t += f", {erg['zusammengefuehrt']} mit Hand-Buchungen zusammengeführt"
    if erg.get("fehler"):
        t += f", {len(erg['fehler'])} nicht lesbar"
    return t


def hochladen(von, b):
    """Datei als base64: CSV wird sofort eingelesen, PDF und Bilder landen im Eingang („wartet auf Auslesen“).
    b: {name, daten (base64), bereich, konto}. → {art, eingang, ergebnis?}"""
    try:
        roh = base64.b64decode(str(b.get("daten") or "").split(",")[-1], validate=True)
    except ValueError:
        raise ValueError("Die Datei ist nicht lesbar (base64 erwartet).")
    if not roh:
        raise ValueError("Die Datei ist leer.")
    if len(roh) > DATEI_MAX:
        raise ValueError("Die Datei ist größer als 10 MB.")
    name = _text(b.get("name"), 120) or "datei"
    art, endung = _art(roh, name)
    bereich = _bereich(b.get("bereich"))
    sha = hashlib.sha256(roh).hexdigest()
    zeilen = info = None
    if art == "csv":
        zeilen, info = csv_lesen(roh, name)   # erst prüfen, dann speichern
    with _sperre:
        d = _lesen()
        alt = next((e for e in d["eingang"] if e.get("sha256") == sha and e["bereich"] == bereich), None)
        if alt and art != "csv":
            return {"art": art, "eingang": alt, "schon_da": True}
        if len(d["eingang"]) >= 5000:
            raise ValueError("Zu viele Dateien im Eingang.")
        e = {"nr": _nr(d["eingang"]), "id": hub.neue_id(d["eingang"]), "name": name, "datei": "", "art": art, "bereich": bereich,
             "konto": _text(b.get("konto"), 60), "bytes": len(roh), "sha256": sha, "von": von, "zeit": _jetzt(), "status": "wartet",
             "erledigt": None, "erledigt_von": "", "ergebnis": "", "buchungen": 0}
        e["datei"] = f"{e['nr']}.{endung}"
        EINGANG.mkdir(parents=True, exist_ok=True)
        (EINGANG / e["datei"]).write_bytes(roh)
        e["ablage"] = ablegen(bereich, "beleg" if art == "bild" else "auszug", name, roh)
        aus, meldung = {"art": art, "eingang": e}, None
        if art == "csv":
            e["konto"] = e["konto"] or info["bank"]
            erg = _einfuegen(d, von, zeilen, "csv", bereich, e["konto"], e["nr"])
            meldung = _nach_buchungen(d, erg["buchungen"])
            saldo = _saldo(zeilen)
            if saldo:
                _konto_setzen(d, von, {"bereich": bereich, "name": e["konto"], "stand_cent": saldo[1], "datum": saldo[0]}, "csv")
            e.update(status="erledigt", erledigt=_jetzt(), erledigt_von=von, buchungen=erg["neu"] + erg["zusammengefuehrt"], ergebnis=_ergebnis_text(erg))
            daten = [b["datum"] for b in zeilen]
            aus["ergebnis"] = {"neu": erg["neu"], "doppelt": erg["doppelt"], "zusammengefuehrt": erg["zusammengefuehrt"], "fehler": erg["fehler"][:20],
                               "uebersprungen": info["uebersprungen"], "bank": info["bank"], "konto": e["konto"], "von": min(daten), "bis": max(daten),
                               "kontostand": saldo[1] if saldo else None, "text": _ergebnis_text(erg)}
        d["eingang"].append(e)
        _schreiben(d)
    _besitzer_melden(meldung)
    return aus


def _saldo(zeilen):
    """Kontostand aus der Saldo-Spalte: die jüngste Buchung (bei gleichem Tag die, die in der Datei zuletzt kam)."""
    Z = [z for z in zeilen if z.get("saldo_cent") is not None]
    if not Z:
        return None
    juengste = max(z["datum"] for z in Z)
    T = [z for z in Z if z["datum"] == juengste]
    z = T[0] if Z[0]["datum"] > Z[-1]["datum"] else T[-1]   # neueste oben: die erste dieses Tages, sonst die letzte
    return z["datum"], z["saldo_cent"]


def eingang_liste(alle=True):
    with _sperre:
        E = _lesen()["eingang"]
    E = sorted(E, key=lambda e: (e["status"] != "wartet", -e["zeit"]))
    return {"eingang": E if alle else [e for e in E if e["status"] == "wartet"], "wartet": sum(1 for e in E if e["status"] == "wartet")}


def eingang_datei(nr):
    with _sperre:
        e = _eingang_finden(_lesen(), nr)
    pfad = EINGANG / e["datei"]
    typ = {"pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg", "webp": "image/webp", "heic": "image/heic", "csv": "text/csv; charset=utf-8"}
    return pfad, typ.get(e["datei"].rsplit(".", 1)[-1], "application/octet-stream")


def eingang_aendern(von, nr, b):
    """Status setzen (erledigt mit Ergebnis, wartet zum Zurückholen) oder Bereich/Konto ändern."""
    with _sperre:
        d = _lesen()
        e = _eingang_finden(d, nr)
        if "bereich" in b:
            e["bereich"] = _bereich(b["bereich"])
        if "konto" in b:
            e["konto"] = _text(b["konto"], 60)
        st = b.get("status")
        if st:
            if st not in ("wartet", "erledigt"):
                raise ValueError("Status muss wartet oder erledigt sein.")
            e["status"] = st
            e["erledigt"], e["erledigt_von"] = (_jetzt(), von) if st == "erledigt" else (None, "")
            if "ergebnis" in b or st == "wartet":
                e["ergebnis"] = _text(b.get("ergebnis"), 500)
        _schreiben(d)
    return e


# ---------- Kontostand ----------

def _konto_finden(d, bereich, name):
    """Konto nach Name oder einem seiner weiteren Namen („auch“). Sichtbare Konten zuerst, damit ein ausgeblendetes nicht wieder auftaucht."""
    n = str(name or "").strip().lower()
    K = [k for k in d["konten"] if k["bereich"] == bereich and n in [k["name"].lower()] + [a.lower() for a in k.get("auch") or []]]
    return next((k for k in K if not k.get("entfernt")), K[0] if K else None)


def _konto_setzen(d, von, b, quelle):
    bereich = _bereich(b.get("bereich"))
    name = _text(b.get("name") or b.get("konto"), 60) or "Konto"
    stand = _cent_feld(b, "stand", pflicht=True)
    datum = _datum_feld(b.get("datum") or heute().isoformat())
    k = _konto_finden(d, bereich, name)
    if k and k.get("datum", "") > datum and quelle != "hand" and not k.get("entfernt"):
        return k   # älterer Auszug überschreibt keinen neueren Stand
    if k:
        k["entfernt"] = None
    else:
        if b.get("entfernen"):
            raise ValueError("Dieses Konto gibt es nicht.")
        k = {"id": hub.neue_id(d["konten"]), "bereich": bereich, "name": name}
        d["konten"].append(k)
    k.update(stand_cent=stand, datum=datum, quelle=quelle, von=von, zeit=_jetzt())
    if isinstance(b.get("auch"), list):
        k["auch"] = [_text(a, 60) for a in b["auch"] if _text(a, 60) and _text(a, 60).lower() != k["name"].lower()][:10]
    return k


def konto_setzen(von, b):
    with _sperre:
        d = _lesen()
        if b.get("entfernen"):   # nur ausblenden, nie löschen
            k = next((k for k in d["konten"] if k["id"] == b.get("id")), None)
            if not k:
                raise ValueError("Dieses Konto gibt es nicht.")
            k["entfernt"], k["entfernt_von"] = _jetzt(), von
            _schreiben(d)
            return k
        k = _konto_setzen(d, von, b, b.get("quelle") or "hand")
        _schreiben(d)
    return k


# ---------- Verträge und Abos ----------

def _monat_cent(v):
    r = v.get("rhythmus") or "monat"
    if r == "woche":
        return round(v["betrag_cent"] * 52 / 12)
    return round(v["betrag_cent"] / RHYTHMEN.get(r, 1))


def _naechste(v, t=None):
    """Nächste Zahlung: angegebenes Datum, in der Vergangenheit um den Rhythmus weitergezählt."""
    t = t or heute()
    s = v.get("naechste_zahlung") or v.get("beginn")
    if not s:
        return ""
    d = date.fromisoformat(s)
    for _ in range(600):
        if d >= t:
            break
        if v.get("rhythmus") == "woche":
            d += timedelta(days=7)
        else:
            n = RHYTHMEN.get(v.get("rhythmus") or "monat") or 1
            m = d.month - 1 + n
            j, m = d.year + m // 12, m % 12 + 1
            d = date(j, m, min(d.day, [31, 29 if j % 4 == 0 and (j % 100 or j % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]))
    return d.isoformat()


def _vertrag_zeigen(v):
    e, n = KAT.get(v["kategorie"], KAT["sonstiges"])
    return dict(v, monat_cent=_monat_cent(v), jahr_cent=_monat_cent(v) * 12, naechste=_naechste(v) if v["status"] == "aktiv" else "", emoji=e, kategorie_name=n)


def _vertrag_felder(v, b, von):
    if "name" in b:
        v["name"] = _text(b["name"], 80, True, "Name")
    if "bereich" in b:
        v["bereich"] = _bereich(b["bereich"])
    c = _cent_feld(b, "betrag", positiv=True)
    if c is not None:
        v["betrag_cent"] = c
    if "rhythmus" in b:
        if b["rhythmus"] not in RHYTHMEN:
            raise ValueError("Rhythmus muss monat, quartal, jahr oder woche sein.")
        v["rhythmus"] = b["rhythmus"]
    if b.get("kategorie"):
        v["kategorie"] = _kat(b["kategorie"])
    for k in ("beginn", "kuendbar_bis", "naechste_zahlung", "testphase_bis"):
        if k in b:
            v[k] = _datum_feld(b[k], pflicht=False)
    if b.get("behalten"):   # Der Besitzer behält es: für diese Frist nicht mehr erinnern
        v["behalten"] = v.get("kuendbar_bis") or ""
    for k, n in (("kuendigungsfrist", 120), ("notiz", 1000), ("hinweis", 60), ("gegenpartei", 80)):
        if k in b:
            v[k] = _text(b[k], n)
    if "status" in b:
        if b["status"] not in ("aktiv", "gekuendigt"):
            raise ValueError("Status muss aktiv oder gekuendigt sein.")
        v["status"] = b["status"]
        if b["status"] == "gekuendigt":
            v["gekuendigt"] = v.get("gekuendigt") or _jetzt()
            v["hinweis"] = "" if v.get("hinweis") == "ungenutzt" else v.get("hinweis", "")
    if b.get("entfernen"):
        v["entfernt"], v["entfernt_von"] = _jetzt(), von
    v["geaendert"] = _jetzt()


def vertrag_neu(von, b):
    with _sperre:
        d = _lesen()
        if len(d["vertraege"]) >= 2000:
            raise ValueError("Zu viele Verträge gespeichert.")
        v = {"id": hub.neue_id(d["vertraege"]), "nr": _nr(d["vertraege"]), "bereich": "privat", "name": "", "betrag_cent": 0, "rhythmus": "monat",
             "kategorie": "abos", "beginn": "", "kuendbar_bis": "", "kuendigungsfrist": "", "naechste_zahlung": "", "notiz": "", "status": "aktiv",
             "hinweis": "", "gegenpartei": "", "von": von, "zeit": _jetzt(), "geaendert": _jetzt(), "entfernt": None}
        if "name" not in b:
            raise ValueError("Name fehlt.")
        if _cent_feld(b, "betrag") is None:
            raise ValueError("Betrag fehlt.")
        _vertrag_felder(v, dict(b, entfernen=False), von)
        if not b.get("kategorie"):
            k, _ = kategorie_raten(v["name"], v["gegenpartei"] or v["name"], -1, d["regeln"])
            v["kategorie"] = k if k not in ("sonstiges", "einnahmen") else "abos"
        v["gegenpartei"] = v["gegenpartei"] or v["name"]
        d["vertraege"].append(v)
        _schreiben(d)
    return _vertrag_zeigen(v)


def vertrag_aendern(von, vid, b):
    with _sperre:
        d = _lesen()
        v = _finden(d["vertraege"], vid, "Diesen Vertrag")
        _vertrag_felder(v, b, von)
        _schreiben(d)
    return _vertrag_zeigen(v)


def _passt(v, k):
    """Gehört der Abo-Schlüssel k (aus Buchungen) zu diesem Vertrag?"""
    for name in (v.get("gegenpartei"), v.get("name")):
        s = schluessel(name)
        if s and (s == k or k.startswith(s + " ") or s.startswith(k + " ") or (len(s.split()[0]) >= 4 and s.split()[0] == k.split()[0])):
            return True
    return False


def vorschlaege(d, bereich):
    """Abo-Erkennung: Ausgaben an dieselbe Gegenpartei mit ähnlichem Betrag in mindestens 2 Monaten, noch nicht als Vertrag eingetragen."""
    G = {}
    for b in _sichtbar(d["buchungen"], bereich):
        if b["betrag_cent"] >= 0 or b["kategorie"] in ("umbuchung", "sparen", "bargeld", "lebensmittel"):
            continue
        k = schluessel(b["gegenpartei"] or gegenpartei_aus_text(b["text"]))
        if k:
            G.setdefault(k, []).append(b)
    V = [v for v in d["vertraege"] if not v.get("entfernt") and v["bereich"] == bereich]
    aus = []
    for k, B in G.items():
        if f"{bereich}|{k}" in d["abo_ignoriert"] or any(_passt(v, k) for v in V):
            continue
        betraege = [-b["betrag_cent"] for b in B]
        mitte = statistics.median(betraege)
        # Abos kosten fast immer gleich viel; Einkäufe (Tanken, Lieferdienst) schwanken und fallen hier heraus
        aehnlich = [b for b in B if abs(-b["betrag_cent"] - mitte) <= max(50, mitte * .02)]
        monate = sorted({b["datum"][:7] for b in aehnlich})
        if len(monate) < 2 or len(aehnlich) > len(monate) + 1 or len(aehnlich) < .6 * len(B):
            continue
        abst = [(int(b[:4]) * 12 + int(b[5:])) - (int(a[:4]) * 12 + int(a[5:])) for a, b in zip(monate, monate[1:])]
        schritt = statistics.median(abst)
        rhythmus = "jahr" if schritt >= 10 else "quartal" if schritt >= 3 else "monat"
        letzte = max(aehnlich, key=lambda b: b["datum"])
        betrag = round(statistics.median([-b["betrag_cent"] for b in aehnlich]))
        n = {"monat": 1, "quartal": 3, "jahr": 12}[rhythmus]
        # Schon als Vertrag da, nur anders benannt („Miete“ statt „Hausverwaltung“)? Gleiche Kategorie und fast gleicher Monatsbetrag.
        if any(v["kategorie"] == letzte["kategorie"] and abs(_monat_cent(v) - round(betrag / n)) <= max(100, betrag / n * .05) for v in V):
            continue
        nd = date.fromisoformat(letzte["datum"])
        m = nd.month - 1 + n
        try:
            naechste = date(nd.year + m // 12, m % 12 + 1, min(nd.day, 28)).isoformat()
        except ValueError:
            naechste = ""
        aus.append({"schluessel": k, "bereich": bereich, "name": letzte["gegenpartei"] or gegenpartei_aus_text(letzte["text"]) or k.title(),
                    "betrag_cent": betrag, "rhythmus": rhythmus, "monate": len(monate), "letzte": letzte["datum"], "kategorie": letzte["kategorie"],
                    "naechste_zahlung": naechste, "monat_cent": round(betrag / n), "buchungen": [b["nr"] for b in aehnlich][-12:]})
    return sorted(aus, key=lambda a: -a["monat_cent"])


def vorschlag_uebernehmen(von, b):
    """Einen Abo-Vorschlag als Vertrag anlegen (b: {bereich, schluessel} und optional Änderungen)."""
    bereich = _bereich(b.get("bereich"))
    with _sperre:
        d = _lesen()
        v = next((v for v in vorschlaege(d, bereich) if v["schluessel"] == b.get("schluessel")), None)
    if not v:
        raise ValueError("Diesen Vorschlag gibt es nicht mehr.")
    kat = v["kategorie"] if v["kategorie"] not in ("sonstiges", "einnahmen") else "abos"
    return vertrag_neu(von, {"bereich": bereich, "name": b.get("name") or v["name"], "betrag_cent": v["betrag_cent"], "rhythmus": v["rhythmus"],
                             "kategorie": b.get("kategorie") or kat, "naechste_zahlung": v["naechste_zahlung"], "gegenpartei": v["schluessel"],
                             "notiz": f"Erkannt aus {v['monate']} Abbuchungen, zuletzt am {date.fromisoformat(v['letzte']).strftime('%d.%m.%Y')}."})


def vorschlag_ignorieren(von, b):
    bereich, k = _bereich(b.get("bereich")), _text(b.get("schluessel"), 80, True, "Schlüssel")
    with _sperre:
        d = _lesen()
        if f"{bereich}|{k}" not in d["abo_ignoriert"]:
            d["abo_ignoriert"].append(f"{bereich}|{k}")
            _schreiben(d)
    return {"ok": True}


# ---------- Sparziele ----------

def ziel_neu(von, b):
    with _sperre:
        d = _lesen()
        if len(d["ziele"]) >= 500:
            raise ValueError("Zu viele Sparziele gespeichert.")
        z = {"id": hub.neue_id(d["ziele"]), "nr": _nr(d["ziele"]), "bereich": _bereich(b.get("bereich")), "name": _text(b.get("name"), 80, True, "Name"),
             "ziel_cent": _cent_feld(b, "ziel", pflicht=True, positiv=True), "stand_cent": _cent_feld(b, "stand", positiv=True) or 0,
             "bis": _datum_feld(b.get("bis"), pflicht=False), "notiz": _text(b.get("notiz"), 500), "verlauf": [], "von": von, "zeit": _jetzt(), "entfernt": None}
        if not z["ziel_cent"]:
            raise ValueError("Das Ziel ist 0 €.")
        z["verlauf"].append({"zeit": _jetzt(), "stand_cent": z["stand_cent"], "von": von})
        d["ziele"].append(z)
        _schreiben(d)
    return z


def ziel_aendern(von, zid, b):
    """Stand setzen (stand), etwas dazulegen oder wegnehmen (dazu, auch negativ), Name, Ziel, Datum ändern, entfernen (Markierung)."""
    with _sperre:
        d = _lesen()
        z = _finden(d["ziele"], zid, "Dieses Sparziel")
        if "name" in b:
            z["name"] = _text(b["name"], 80, True, "Name")
        if "bereich" in b:
            z["bereich"] = _bereich(b["bereich"])
        c = _cent_feld(b, "ziel", positiv=True)
        if c:
            z["ziel_cent"] = c
        if "bis" in b:
            z["bis"] = _datum_feld(b["bis"], pflicht=False)
        if "notiz" in b:
            z["notiz"] = _text(b["notiz"], 500)
        alt = z["stand_cent"]
        s = _cent_feld(b, "stand", positiv=True)
        if s is not None:
            z["stand_cent"] = s
        dz = _cent_feld(b, "dazu")
        if dz:
            z["stand_cent"] = max(0, z["stand_cent"] + dz)
        if z["stand_cent"] != alt:
            z["verlauf"] = (z["verlauf"] + [{"zeit": _jetzt(), "stand_cent": z["stand_cent"], "von": von}])[-100:]
        if b.get("entfernen"):
            z["entfernt"], z["entfernt_von"] = _jetzt(), von
        _schreiben(d)
    return z


# ---------- Berater: Tipps ----------

def tipp_neu(von, b):
    with _sperre:
        d = _lesen()
        if len(d["tipps"]) >= 3000:
            d["tipps"] = [t for t in d["tipps"] if not t["erledigt"]] + [t for t in d["tipps"] if t["erledigt"]][-1000:]
        t = {"id": hub.neue_id(d["tipps"]), "nr": _nr(d["tipps"]), "bereich": _bereich(b.get("bereich")), "text": _text(b.get("text"), 1000, True),
             "art": "agent", "von": von, "zeit": _jetzt(), "erledigt": None}
        d["tipps"].append(t)
        _schreiben(d)
    return t


def tipp_aendern(von, tid, b):
    """Abhaken (erledigt: true/false). Geht auch für die eingebauten Hinweise (id beginnt mit „r“)."""
    an = b.get("erledigt", True) is not False
    with _sperre:
        d = _lesen()
        if str(tid).startswith("r") and len(str(tid)) == 11:
            if an:
                d["regel_erledigt"][tid] = _jetzt()
            else:
                d["regel_erledigt"].pop(tid, None)
            _schreiben(d)
            return {"id": tid, "erledigt": d["regel_erledigt"].get(tid)}
        t = _finden(d["tipps"], tid, "Diesen Tipp")
        t["erledigt"], t["erledigt_von"] = (_jetzt(), von) if an else (None, "")
        _schreiben(d)
    return t


_ABO_ARTEN = [("Streaming", "netflix disney* dazn sky prime video amazon prime joyn wow tv apple tv"), ("Musik", "spotify apple music deezer tidal youtube music"),
              ("Cloud-Speicher", "icloud google one dropbox onedrive"), ("KI", "chatgpt openai anthropic claude.ai midjourney"),
              ("Handy", "a1 magenta drei spusu yesss hofer telekom")]
_ABO_ARTEN = [(n, _muster(w)) for n, w in _ABO_ARTEN]


def _werte(B):
    ein = sum(b["betrag_cent"] for b in B if b["kategorie"] == "einnahmen")
    aus = -sum(b["betrag_cent"] for b in B if b["kategorie"] not in NICHT_AUSGABE)
    spar = -sum(b["betrag_cent"] for b in B if b["kategorie"] == "sparen")
    return {"einnahmen_cent": ein, "ausgaben_cent": aus, "sparen_cent": spar, "gespart_cent": ein - aus,
            "sparquote": round(100 * (ein - aus) / ein) if ein > 0 else None, "anzahl": len(B)}


def _kats(B):
    S = {}
    for b in B:
        if b["kategorie"] in NICHT_AUSGABE:
            continue
        s = S.setdefault(b["kategorie"], {"key": b["kategorie"], "emoji": KAT.get(b["kategorie"], KAT["sonstiges"])[0],
                                          "name": KAT.get(b["kategorie"], KAT["sonstiges"])[1], "summe_cent": 0, "anzahl": 0})
        s["summe_cent"] -= b["betrag_cent"]
        s["anzahl"] += 1
    return sorted(S.values(), key=lambda s: -s["summe_cent"])


def _regel_tipps(d, bereich, t=None):
    t = t or heute()
    tipps = []

    def neu(schl, text, art):
        tid = "r" + hashlib.sha1(schl.encode()).hexdigest()[:10]
        tipps.append({"id": tid, "bereich": bereich, "text": text, "art": art, "von": "zentrale", "zeit": None, "erledigt": d["regel_erledigt"].get(tid)})
    B = _sichtbar(d["buchungen"], bereich)
    m, vm, vvm = t.strftime("%Y-%m"), _monat_plus(t.strftime("%Y-%m"), -1), _monat_plus(t.strftime("%Y-%m"), -2)
    imMonat = lambda mo: [b for b in B if b["datum"].startswith(mo)]

    def grund(jetzt, vorher):
        a, v = {k["key"]: k for k in _kats(jetzt)}, {k["key"]: k["summe_cent"] for k in _kats(vorher)}
        if not a:
            return ""
        k = max(a.values(), key=lambda k: k["summe_cent"] - v.get(k["key"], 0))
        diff = k["summe_cent"] - v.get(k["key"], 0)
        if diff <= 0:
            return ""
        gp = {}
        for b in jetzt:
            if b["kategorie"] == k["key"] and b["betrag_cent"] < 0:
                g = b["gegenpartei"] or gegenpartei_aus_text(b["text"])
                gp[g] = gp.get(g, 0) - b["betrag_cent"]
        top = max(gp, key=gp.get) if gp else ""
        return f" Größter Unterschied: {k['emoji']} {k['name']} (+{eur(diff)}{', vor allem ' + top if top else ''})."

    w_m, w_vm, w_vvm = _werte(imMonat(m)), _werte(imMonat(vm)), _werte(imMonat(vvm))
    if w_vm["anzahl"] and w_m["ausgaben_cent"] > w_vm["ausgaben_cent"] > 0:
        neu(f"monat|{bereich}|{m}", f"{_monat_name(m, False)} bisher: {eur(w_m['ausgaben_cent'])} ausgegeben, schon {eur(w_m['ausgaben_cent'] - w_vm['ausgaben_cent'])} mehr "
            f"als im ganzen {_monat_name(vm, False)}." + grund(imMonat(m), imMonat(vm)), "monat")
    elif w_vvm["anzahl"] and w_vm["ausgaben_cent"] > w_vvm["ausgaben_cent"] * 1.15 and w_vm["ausgaben_cent"] - w_vvm["ausgaben_cent"] > 5000:
        neu(f"monat|{bereich}|{vm}", f"Im {_monat_name(vm, False)} hast du {eur(w_vm['ausgaben_cent'] - w_vvm['ausgaben_cent'])} mehr ausgegeben als im "
            f"{_monat_name(vvm, False)} ({eur(w_vm['ausgaben_cent'])} statt {eur(w_vvm['ausgaben_cent'])})." + grund(imMonat(vm), imMonat(vvm)), "monat")
    if w_vm["einnahmen_cent"] > 0 and w_vm["gespart_cent"] < 0:
        neu(f"minus|{bereich}|{vm}", f"Im {_monat_name(vm, False)} ist mehr hinausgegangen als hereingekommen: {eur(w_vm['gespart_cent'])}. "
            "Schau dir die größten Posten im Haushaltsbuch an.", "minus")
    V = [v for v in d["vertraege"] if not v.get("entfernt") and v["bereich"] == bereich and v["status"] == "aktiv"]
    for v in V:
        if "ungenutzt" in (v.get("hinweis") or "").lower():
            neu(f"ungenutzt|{v['id']}", f"{v['name']} ist als ungenutzt markiert und kostet {eur(_monat_cent(v))} im Monat. "
                f"Kündigen spart {eur(_monat_cent(v) * 12)} im Jahr." + (f" Kündigungsfrist: {v['kuendigungsfrist']}." if v.get("kuendigungsfrist") else ""), "abo")
        if v.get("kuendbar_bis"):
            tage = (date.fromisoformat(v["kuendbar_bis"]) - t).days
            if 0 <= tage <= 30:
                neu(f"kuendbar|{v['id']}|{v['kuendbar_bis']}", f"{v['name']} ist nur noch bis {date.fromisoformat(v['kuendbar_bis']).strftime('%d.%m.')} kündbar "
                    f"({'heute' if tage == 0 else 'morgen' if tage == 1 else f'in {tage} Tagen'}). Brauchst du das noch? Es kostet {eur(_monat_cent(v) * 12)} im Jahr.", "frist")
    for art, mu in _ABO_ARTEN:
        X = [v for v in V if mu.search(f"{v['name']} {v.get('gegenpartei', '')}")]
        if len(X) >= 2:
            summe = sum(_monat_cent(v) for v in X)
            neu(f"doppelt|{bereich}|{art}|{','.join(sorted(v['id'] for v in X))}", f"Du zahlst {len(X)} Abos für {art}: {', '.join(v['name'] for v in X)} "
                f"({eur(summe)} im Monat). Reicht eines? Das spart bis zu {eur((summe - min(_monat_cent(v) for v in X)) * 12)} im Jahr.", "abo")
    VS = vorschlaege(d, bereich)
    if VS:
        neu(f"vorschlag|{bereich}|{','.join(sorted(v['schluessel'] for v in VS))}", f"{len(VS)} wiederkehrende {'Zahlung' if len(VS) == 1 else 'Zahlungen'} "
            f"noch nicht als Abo eingetragen: {', '.join(v['name'] for v in VS[:4])}{' und weitere' if len(VS) > 4 else ''}. Unter Verträge und Abos kannst du sie übernehmen.", "vorschlag")
    return tipps


def tipps(bereich=None, alle=False):
    with _sperre:
        d = _lesen()
    T = []
    for b in ([_bereich(bereich)] if bereich else BEREICHE):
        T += _regel_tipps(d, b)
        T += [t for t in d["tipps"] if t["bereich"] == b]
    if not alle:
        T = [t for t in T if not t["erledigt"]]
    return sorted(T, key=_tipp_folge)


def _tipp_folge(t):
    """Offene zuerst, darin die Tipps der Agenten (neueste oben), dann die eingebauten Hinweise."""
    return (bool(t["erledigt"]), t.get("art") == "regel", -(t["zeit"] or 0))


# ---------- Überblick und Monat (Haushaltsbuch) ----------

def ueberblick(bereich="privat", monat=None):
    bereich, m = _bereich(bereich), _monat(monat)
    with _sperre:
        d = _lesen()
    B = _sichtbar(d["buchungen"], bereich)
    K = [k for k in d["konten"] if k["bereich"] == bereich and not k.get("entfernt")]
    V = sorted((_vertrag_zeigen(v) for v in d["vertraege"] if not v.get("entfernt") and v["bereich"] == bereich),
               key=lambda v: (v["status"] != "aktiv", -v["monat_cent"]))
    Z = [z for z in d["ziele"] if not z.get("entfernt") and z["bereich"] == bereich]
    R = sorted((_rechnung_zeigen(r) for r in d["rechnungen"] if not r.get("entfernt") and r["bereich"] == bereich and r["status"] == "offen"),
               key=lambda r: (r["faellig"] or "9999", r["nr"]))
    T = _regel_tipps(d, bereich) + [t for t in d["tipps"] if t["bereich"] == bereich]
    verlauf = []
    for i in range(5, -1, -1):
        mo = _monat_plus(m, -i)
        w = _werte([b for b in B if b["datum"].startswith(mo)])
        verlauf.append({"monat": mo, "name": _monat_name(mo, False), "einnahmen_cent": w["einnahmen_cent"], "ausgaben_cent": w["ausgaben_cent"]})
    imMonat = [b for b in B if b["datum"].startswith(m)]
    E = d["eingang"]
    return {"bereich": bereich, "monat": m, "monat_name": _monat_name(m), "heute": heute().isoformat(),
            "kontostand": {"summe_cent": sum(k["stand_cent"] for k in K), "konten": sorted(K, key=lambda k: k["name"].lower()),
                           "datum": min((k["datum"] for k in K), default="")},
            "werte": _werte(imMonat), "verlauf": verlauf, "kategorien": _kats(imMonat),
            "vertraege": V, "vertraege_monat_cent": sum(v["monat_cent"] for v in V if v["status"] == "aktiv"),
            "vorschlaege": vorschlaege(d, bereich), "ziele": sorted(Z, key=lambda z: z["nr"]),
            "rechnungen": R, "rechnungen_cent": sum(r["betrag_cent"] for r in R), "ordner": str(ORDNER),
            "tipps": sorted([t for t in T if not t["erledigt"]], key=_tipp_folge), "tipps_erledigt": sum(1 for t in T if t["erledigt"]),
            "eingang_wartet": sum(1 for e in E if e["status"] == "wartet" and e["bereich"] == bereich),
            "buchungen_gesamt": len(B), "neueste": [_zeigen(b) for b in sorted(B, key=lambda b: (b["datum"], b["nr"]), reverse=True)[:5]],
            "erste": min((b["datum"] for b in B), default=""), "letzte": max((b["datum"] for b in B), default=""),
            "kategorien_liste": kategorien(), "fristen": _fristen(d, bereich)}


def monat_ansicht(bereich="privat", monat=None):
    bereich, m = _bereich(bereich), _monat(monat)
    with _sperre:
        d = _lesen()
    B = _sichtbar(d["buchungen"], bereich)
    imMonat = sorted((b for b in B if b["datum"].startswith(m)), key=lambda b: (b["datum"], b["nr"]), reverse=True)
    E = [e for e in d["eingang"] if e["bereich"] == bereich]
    return {"bereich": bereich, "monat": m, "monat_name": _monat_name(m), "vormonat": _monat_plus(m, -1), "naechster": _monat_plus(m, 1),
            "werte": _werte(imMonat), "kategorien": _kats(imMonat), "buchungen": [_zeigen(b) for b in imMonat],
            "eingang": sorted(E, key=lambda e: (e["status"] != "wartet", -e["zeit"]))[:20], "buchungen_gesamt": len(B),
            "letzte": max((b["datum"] for b in B), default=""), "kategorien_liste": kategorien()}


# ---------- Offene Rechnungen (nachzahlen, wenn der Lohn kommt) ----------

_LOHN = re.compile(r"(?i)\b(lohn|loh|gehalt|bezug|bezüge|bezuege)\b")


def _rechnung_zeigen(r):
    return dict(r, ueberfaellig=bool(r["status"] == "offen" and r.get("faellig") and r["faellig"] < heute().isoformat()))


def _rechnung_felder(r, b, von):
    if "name" in b:
        r["name"] = _text(b["name"], 80, True, "Name")
    if "bereich" in b:
        r["bereich"] = _bereich(b["bereich"])
    c = _cent_feld(b, "betrag", positiv=True)
    if c is not None:
        r["betrag_cent"] = c
    if "faellig" in b:
        r["faellig"] = _datum_feld(b["faellig"], pflicht=False)
    for k, n in (("rechnungsnr", 60), ("gegenpartei", 80), ("notiz", 1000)):
        if k in b:
            r[k] = _text(b[k], n)
    if "link" in b:
        link = _text(b["link"], 500)
        if link and not re.match(r"^https://", link):
            raise ValueError("Der Link muss mit https:// beginnen.")
        r["link"] = link
    if "bei_lohn" in b:
        r["bei_lohn"] = bool(b["bei_lohn"])
    if "bezahlt" in b:
        if b["bezahlt"]:
            r.update(status="bezahlt", bezahlt=r.get("bezahlt") or _jetzt(), bezahlt_von=von)
        else:
            r.update(status="offen", bezahlt=None, bezahlt_von="", buchung=None)
    if b.get("entfernen"):
        r["entfernt"], r["entfernt_von"] = _jetzt(), von
    r["geaendert"] = _jetzt()


def rechnung_neu(von, b, dateien=None):
    """Offene Rechnung eintragen. Gleiche Rechnungsnummer = dieselbe Rechnung (wird nur ergänzt)."""
    with _sperre:
        d = _lesen()
        nr = _text(b.get("rechnungsnr"), 60)
        # Gleiche Rechnung = gleiche Nummer UND gleicher Bereich UND gleicher Aussteller (Prüfung 31.10.2026, F-02).
        # Rechnungsnummern sind nur je Aussteller eindeutig; „2026-001“ gibt es bei vielen Firmen.
        gleich = [r for r in d["rechnungen"] if nr and r.get("rechnungsnr") == nr and not r.get("entfernt")]
        if "name" in b or "gegenpartei" in b or "bereich" in b:
            wer = schluessel(b.get("gegenpartei") or b.get("name"))
            bereich = _bereich(b["bereich"]) if b.get("bereich") else None
            gleich = [r for r in gleich if (not bereich or r["bereich"] == bereich) and (not wer or schluessel(r["gegenpartei"] or r["name"]) == wer)]
        if len(gleich) > 1:
            raise ValueError(f"Rechnungsnummer {nr} passt zu mehreren Rechnungen. Bitte mit der Rechnungs-Nummer der Zentrale ändern.")
        r = gleich[0] if gleich else None
        if not r:
            if len(d["rechnungen"]) >= 5000:
                raise ValueError("Zu viele Rechnungen gespeichert.")
            if "name" not in b or _cent_feld(b, "betrag") is None:
                raise ValueError("Name und Betrag fehlen.")
            r = {"id": hub.neue_id(d["rechnungen"]), "nr": _nr(d["rechnungen"]), "bereich": "privat", "name": "", "betrag_cent": 0, "faellig": "",
                 "rechnungsnr": "", "gegenpartei": "", "link": "", "notiz": "", "dateien": [], "bei_lohn": True, "status": "offen",
                 "bezahlt": None, "bezahlt_von": "", "buchung": None, "von": von, "zeit": _jetzt(), "geaendert": _jetzt(), "entfernt": None}
            d["rechnungen"].append(r)
        _rechnung_felder(r, dict(b, entfernen=False, bezahlt=b.get("bezahlt", r["status"] == "bezahlt")), von)
        r["gegenpartei"] = r["gegenpartei"] or r["name"]
        r["dateien"] = list(dict.fromkeys(r["dateien"] + [x for x in dateien or [] if x]))
        _schreiben(d)
    return _rechnung_zeigen(r)


def rechnung_aendern(von, rid, b):
    with _sperre:
        d = _lesen()
        r = _finden(d["rechnungen"], rid, "Diese Rechnung")
        _rechnung_felder(r, b, von)
        _schreiben(d)
    return _rechnung_zeigen(r)


def _nach_buchungen(d, neu):
    """Nach neuen Buchungen: passende offene Rechnungen als bezahlt markieren (gleicher Betrag, Name im Text, nicht vor der Rechnung)
    und merken, ob gerade Lohn gekommen ist. → Text für den Besitzer oder None."""
    R = [r for r in d["rechnungen"] if r["status"] == "offen" and not r.get("entfernt")]
    gezahlt, lohn = [], None
    for x in neu:
        if x["betrag_cent"] < 0:
            # Nur gleicher Bereich (Privat/Firma) und nur, wenn genau eine offene Rechnung passt (Prüfung 31.10.2026, F-03)
            passend = []
            for r in R:
                w = schluessel(r["gegenpartei"] or r["name"]).split()
                ab = date.fromtimestamp(r["zeit"]) - timedelta(days=3)
                if (r["status"] == "offen" and r["bereich"] == x["bereich"] and -x["betrag_cent"] == r["betrag_cent"] and w
                        and w[0] in schluessel(x["gegenpartei"] + " " + x["text"]) and x["datum"] >= ab.isoformat()):
                    passend.append(r)
            if len(passend) == 1:
                passend[0].update(status="bezahlt", bezahlt=_jetzt(), bezahlt_von="zentrale", buchung=x["nr"])
                gezahlt.append(passend[0])
        elif (x["kategorie"] == "einnahmen" and x["bereich"] == "privat" and x["datum"] >= (heute() - timedelta(days=10)).isoformat()
              and (x["betrag_cent"] >= 150000 or (x["betrag_cent"] >= 30000 and _LOHN.search(x["text"])))):
            lohn = x
    teile = [f"✅ {r['name']} {eur(r['betrag_cent'])} ist bezahlt (Buchung Nr. {r['buchung']})." for r in gezahlt]
    offen = [r for r in R if r["status"] == "offen" and r["bei_lohn"]]
    if lohn and offen:
        zeilen = [f"• {r['name']}: {eur(r['betrag_cent'])}" + (f" (fällig {date.fromisoformat(r['faellig']).strftime('%d.%m.')})" if r.get("faellig") else "")
                  + (f"\n  Bezahlen: {r['link']}" if r.get("link") else "") for r in offen]
        teile.append(f"💶 Lohn ist da: {eur(lohn['betrag_cent'])} am {date.fromisoformat(lohn['datum']).strftime('%d.%m.')}\n"
                     f"Jetzt nachzahlen ({eur(sum(r['betrag_cent'] for r in offen))}):\n" + "\n".join(zeilen)
                     + "\nIst es bezahlt: unter Finanzen bei der Rechnung auf „Bezahlt“ tippen.")
    return "\n\n".join(teile) or None


def _besitzer_melden(text):
    """Hinweis an den Besitzer (Rechnung bezahlt, Lohn da): als Bericht von der Zentrale, ohne Frage."""
    if not text:
        return
    try:
        import berichte
        erste = text.strip().splitlines()[0][:120]
        berichte.neu("zentrale", {"titel": "Finanzen: " + erste.lstrip("✅💶 ").rstrip("."), "kurz": text[:1000], "projekt": "Finanzen"})
    except Exception:
        pass


RHYTHMUS_TEXT = {"monat": "im Monat", "quartal": "im Quartal", "jahr": "im Jahr", "woche": "in der Woche"}


def _fristen(d, bereich=None, t=None, bis=30):
    """Aktive Verträge mit „kündbar bis“ in 0 bis `bis` Tagen, für die der Besitzer nicht „behalten“ gesagt hat."""
    t, aus = t or heute(), []
    for v in d["vertraege"]:
        if v.get("entfernt") or v["status"] != "aktiv" or not v.get("kuendbar_bis") or v.get("behalten") == v["kuendbar_bis"] or (bereich and v["bereich"] != bereich):
            continue
        tage = (date.fromisoformat(v["kuendbar_bis"]) - t).days
        if 0 <= tage <= bis:
            aus.append(dict(_vertrag_zeigen(v), tage=tage))
    return sorted(aus, key=lambda v: v["tage"])


def fristen():
    with _sperre:
        return _fristen(_lesen())


# ---------- Ablage: alles in einem Ordner ----------

def _dateiname(s):
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", str(s or "")).strip(" .")
    return re.sub(r"\s+", " ", s)[:140] or "Datei"


def ablegen(bereich, art, name, roh, datum=None):
    """Datei in den Finanz-Ordner legen: <Bereich>/<Kontoauszüge|Belege|Rechnungen>/<Jahr>/<Datum> <Name>. → Pfad relativ zum Ordner
    oder "", wenn der Ordner nicht beschreibbar ist (dann bleibt die Datei trotzdem im Eingang der Zentrale)."""
    datum = datum or heute().isoformat()
    ziel = ORDNER / _bereich(bereich).capitalize() / ABLAGE[art] / datum[:4]
    n = _dateiname(name)
    n = n if n.startswith(datum) else f"{datum} {n}"
    try:
        ziel.mkdir(parents=True, exist_ok=True)
        stamm, endung = os.path.splitext(n)
        p, i = ziel / n, 2
        while p.exists():
            if p.read_bytes() == roh:
                return str(p.relative_to(ORDNER))
            p, i = ziel / f"{stamm} ({i}){endung}", i + 1
        tmp = p.with_name(f".{p.name}.tmp")
        tmp.write_bytes(roh)
        tmp.replace(p)
        return str(p.relative_to(ORDNER))
    except OSError:
        return ""


_export = {"geplant": False}


def _export_spaeter():
    if not _export["geplant"]:
        _export["geplant"] = True
        threading.Timer(5, _exportieren).start()


def _zelle(t):
    """Text für eine CSV-Zelle, die Excel und Numbers nie als Formel lesen (Prüfung 31.10.2026, S-05): Beginnt er mit
    = + - @ oder einem Steuerzeichen, kommt ein Hochkomma davor. Beträge laufen nicht hier durch und bleiben Zahlen."""
    t = str(t or "")
    return "'" + t if t[:1] in ("=", "+", "-", "@", "\t", "\r", "\n") or t.lstrip()[:1] in ("=", "+", "-", "@") else t


def _cent_text(c):
    return f"{c / 100:.2f}".replace(".", ",")


def _exportieren():
    """Haushaltsbuch.csv und Übersicht.md je Bereich neu schreiben, Dateien aus dem Eingang nachträglich ablegen."""
    _export["geplant"] = False
    try:
        if not ORDNER.parent.is_dir():
            return
        with _sperre:
            d = _lesen()
            neu = False
            for e in d["eingang"]:
                if e.get("ablage") is None:
                    try:
                        roh = (EINGANG / e["datei"]).read_bytes()
                    except OSError:
                        continue
                    e["ablage"] = ablegen(e["bereich"], "beleg" if e["art"] == "bild" else "auszug", e["name"], roh, date.fromtimestamp(e["zeit"]).isoformat())
                    neu = neu or bool(e["ablage"])
            if neu:
                tmp = DATEI.with_name(DATEI.name + ".tmp")
                tmp.write_text(json.dumps(d, ensure_ascii=False))
                tmp.replace(DATEI)
        for bereich in BEREICHE:
            B = sorted(_sichtbar(d["buchungen"], bereich), key=lambda b: (b["datum"], b["nr"]))
            K = [k for k in d["konten"] if k["bereich"] == bereich and not k.get("entfernt")]
            R = [r for r in d["rechnungen"] if r["bereich"] == bereich and not r.get("entfernt")]
            V = [_vertrag_zeigen(v) for v in d["vertraege"] if v["bereich"] == bereich and not v.get("entfernt") and v["status"] == "aktiv"]
            Z = [z for z in d["ziele"] if z["bereich"] == bereich and not z.get("entfernt")]
            if not (B or K or R or V or Z):
                continue
            ziel = ORDNER / bereich.capitalize()
            ziel.mkdir(parents=True, exist_ok=True)
            f = io.StringIO()
            w = csv.writer(f, delimiter=";", lineterminator="\r\n")
            w.writerow(["Nr", "Datum", "Betrag €", "Text", "Gegenpartei", "Kategorie", "Konto", "Quelle", "Notiz"])
            for b in B:
                w.writerow([b["nr"], b["datum"], _cent_text(b["betrag_cent"]), _zelle(b["text"]), _zelle(b["gegenpartei"]),
                            _zelle(KAT.get(b["kategorie"], ("", b["kategorie"]))[1]), _zelle(b["konto"]), b["quelle"], _zelle(b["notiz"])])
            (ziel / ".Haushaltsbuch.csv.tmp").write_text(f.getvalue(), encoding="utf-8-sig")
            (ziel / ".Haushaltsbuch.csv.tmp").replace(ziel / "Haushaltsbuch.csv")
            t = [f"# Finanzen {bereich.capitalize()}", "", f"Stand: {time.strftime('%d.%m.%Y %H:%M')}. Wird von der Zentrale geschrieben, Änderungen hier gehen verloren.", ""]
            if K:
                t += ["## Kontostand", ""] + [f"- {k['name']}: {eur(k['stand_cent'])} (vom {date.fromisoformat(k['datum']).strftime('%d.%m.%Y')})" for k in K] + [""]
            offen = [r for r in R if r["status"] == "offen"]
            t += ["## Offene Rechnungen", ""] + ([f"- {r['name']}: {eur(r['betrag_cent'])}" + (f", fällig {date.fromisoformat(r['faellig']).strftime('%d.%m.%Y')}" if r["faellig"] else "")
                                                 + (f", Rechnung {r['rechnungsnr']}" if r["rechnungsnr"] else "") + (f", [bezahlen]({r['link']})" if r["link"] else "")
                                                 for r in offen] or ["- keine"]) + [""]
            if V:
                t += ["## Verträge und Abos", ""] + [f"- {v['name']}: {eur(v['betrag_cent'])} je {v['rhythmus']}" for v in V] + [""]
            if Z:
                t += ["## Sparziele", ""] + [f"- {z['name']}: {eur(z['stand_cent'])} von {eur(z['ziel_cent'])}" for z in Z] + [""]
            t += ["## Ordner", "", "- Kontoauszüge, Belege, Rechnungen: je Jahr ein Unterordner", "- Haushaltsbuch.csv: alle Buchungen (Excel, Numbers)", ""]
            (ziel / ".Übersicht.md.tmp").write_text("\n".join(t))
            (ziel / ".Übersicht.md.tmp").replace(ziel / "Übersicht.md")
    except Exception:
        pass


# ---------- Schnittstelle (app.py ruft nur diese beiden auf) ----------

UPLOAD_MAX = 15 * 1024 * 1024   # 10 MB Datei als base64 im JSON


def _auftrag(e):
    """Der Besitzer hat einen PDF-Auszug oder ein Bild hochgeladen: Aufgabe für Claude, es auszulesen und zu buchen."""
    try:
        import pos
        art = "Kontoauszug (PDF)" if e["art"] == "pdf" else "Bild"
        pos.aufgabe_neu("zentrale", {"titel": f"Finanz-Eingang Nr. {e['nr']} auslesen und buchen ({art}, {e['bereich']})", "fuer": "claude",
                                     "notiz": f"„{e['name']}“. Holen: finanz-eingang-holen {e['nr']} --ziel finanz-{e['nr']}.{e['datei'].rsplit('.', 1)[-1]}, "
                                              f"lesen, dann buchungen-eintragen --datei buchungen.json --eingang {e['nr']}. Dem Besitzer kurz melden, was auffällt."})
    except Exception:
        pass


def api_get(teile, q):
    """GET /api/finanzen/… → („json“, obj) oder („datei“, bytes, typ). None = unbekannt."""
    w = lambda k, s="": (q.get(k) or [s])[0]
    if not teile:
        return "json", ueberblick(w("bereich", "privat"), w("monat"))
    if teile == ["monat"]:
        return "json", monat_ansicht(w("bereich", "privat"), w("monat"))
    if teile == ["buchungen"]:
        return "json", buchungen(w("bereich") or None, w("monat") or None, w("kategorie") or None, w("q") or None, w("anzahl", "500"))
    if teile == ["tipps"]:
        return "json", {"tipps": tipps(w("bereich") or None, w("alle") == "1")}
    if teile == ["fristen"]:
        return "json", {"fristen": fristen()}
    if teile == ["kategorien"]:
        return "json", {"kategorien": kategorien()}
    if teile == ["verstehen"]:
        return "json", satz_verstehen(w("text"), w("bereich") or None)
    if teile == ["eingang"]:
        return "json", eingang_liste(w("alle", "1") != "0")
    if teile == ["rechnungen"]:
        with _sperre:
            R = _lesen()["rechnungen"]
        alle = w("alle") == "1"
        return "json", {"rechnungen": [_rechnung_zeigen(r) for r in sorted(R, key=lambda r: -r["nr"]) if not r.get("entfernt") and (alle or r["status"] == "offen")]}
    if len(teile) == 3 and teile[0] == "eingang" and teile[2] == "datei":
        pfad, typ = eingang_datei(teile[1])
        try:
            return "datei", pfad.read_bytes(), typ
        except OSError:
            raise ValueError("Die Datei fehlt im Eingang.")
    return None


def api_post(von, teile, b):
    """POST /api/finanzen/… → Antwort oder None (unbekannt)."""
    if not isinstance(b, dict):
        raise ValueError("JSON-Objekt erwartet.")
    t = teile + [""] * (2 - len(teile))
    if len(teile) > 2:
        return None
    if t == ["upload", ""]:
        r = hochladen(von, b)
        if von == B and r["art"] != "csv" and not r.get("schon_da"):
            threading.Thread(target=_auftrag, args=(dict(r["eingang"]),), daemon=True).start()
        return r
    if t == ["satz", ""]:
        return satz_buchen(von, b)
    if t[0] == "buchungen":
        return buchung_neu(von, b) if not t[1] else buchungen_menge(von, b) if t[1] == "menge" else buchung_aendern(von, t[1], b)
    if t[0] == "eingang" and t[1]:
        return eingang_aendern(von, t[1], b)
    if t == ["konto", ""]:
        return konto_setzen(von, b)
    if t[0] == "vertraege":
        return vertrag_aendern(von, t[1], b) if t[1] else vertrag_neu(von, b)
    if t == ["vorschlaege", "uebernehmen"]:
        return vorschlag_uebernehmen(von, b)
    if t == ["vorschlaege", "ignorieren"]:
        return vorschlag_ignorieren(von, b)
    if t[0] == "ziele":
        return ziel_aendern(von, t[1], b) if t[1] else ziel_neu(von, b)
    if t[0] == "tipps":
        return tipp_aendern(von, t[1], b) if t[1] else tipp_neu(von, b)
    if t[0] == "rechnungen":
        return rechnung_aendern(von, t[1], b) if t[1] else rechnung_neu(von, b)
    return None
