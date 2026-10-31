#!/usr/bin/env python3
r"""Anschluss an die Zentrale für Agenten (Claude Code, Codex, eigene Skripte). Braucht nur Python 3.

Schlüssel: `py start.py agent-neu codex` legt ihn in %USERPROFILE%\.config\zentrale-starter\codex.key ab
(Mac und Linux: ~/.config/zentrale-starter/). Der Client nimmt --schluessel, sonst ZENTRALE_SCHLUESSEL, sonst die Datei
zu --agent (oder ZENTRALE_AGENT), sonst die einzige .key-Datei im Ordner. Jeder Agent gibt immer seinen eigenen Namen an:
Claude `--agent claude`, Codex `--agent codex`. Adresse: --url oder ZENTRALE_URL, Standard http://127.0.0.1:8090.
Unter Windows heißt es `py` (oder `python`), am Mac und unter Linux `python3`. Textdateien dürfen mit BOM kommen
(PowerShell 5 schreibt so).

Wünsche (jeden echten Auftrag des Besitzers sofort eintragen, immer mit Priorität):
  py zentrale_client.py --agent codex wuensche
  py zentrale_client.py --agent codex wunsch "Fotos ordnen" --text "nach Jahr" --gruppe Aufräumen --prio hoch
  py zentrale_client.py --agent codex wunsch-zeigen 3                     (Text, Ergebnis, alle Notizen; vor der Arbeit lesen)
  py zentrale_client.py --agent codex wunsch-notiz 3 "Stand: … · Als Nächstes: … · Wartet auf: …"
  py zentrale_client.py --agent codex wunsch-erledigt 3 --ergebnis "Fotos liegen unter Bilder/<Jahr>."
  py zentrale_client.py --agent codex wunsch-prio 3 mittel

Projekte und Aufgaben:
  py zentrale_client.py --agent codex projekte
  py zentrale_client.py --agent codex projekt-neu "Website" --beschreibung "…" --ort "Laptop:C:\Users\<Name>\Projekte\Website"
  py zentrale_client.py --agent codex projekt-schritt Website "Texte für die Startseite"
  py zentrale_client.py --agent codex projekt-status Website ruht            (aktiv, ruht, archiv)
  py zentrale_client.py --agent codex aufgabe "Impressum prüfen" --projekt Website --faellig 2030-01-31 --wunsch 3 --fuer besitzer
  py zentrale_client.py --agent codex aufgabe-erledigt a1b2c3

Berichte an den Besitzer, mit Fragen und Vorschlägen:
  py zentrale_client.py --agent codex bericht-neu "Plan: Ordner aufräumen" --kurz "Drei Schritte." --text-datei plan.md `
      --frage "Passt der Plan?" --vorschlaege "Ja|Nein" --frage "Alte Downloads in den Papierkorb?" --vorschlaege "Ja|Später"
      Je Frage ein eigenes --frage: Der Besitzer bekommt sie nacheinander. Fragen nie in --kurz oder in den Text schreiben.
  py zentrale_client.py --agent codex berichte                 (offene Fragen und neue Antworten zuerst)
  py zentrale_client.py --agent codex bericht 4                (ein Bericht mit Verlauf)
  py zentrale_client.py --agent codex bericht-antwort 4 "Danke, ich fange an."
  py zentrale_client.py --agent codex bericht-erledigt 4 --antwort "Ja" --antwort "Später"   (im Chat beantwortet: so schließen)
  py zentrale_client.py --agent codex berichte-warten [--sitzung <id>] [--max 600]
      wartet, bis der Besitzer in einem eigenen Bericht schreibt, gibt die Nachrichten aus und endet (Code 0, ohne Nachricht Code 3).

Läufe: was du gerade machst (Seite „Agenten“). Claude meldet sich über den Hook von selbst, Codex so:
  py zentrale_client.py --agent codex lauf start "Downloads aufräumen" --wunsch 7
  py zentrale_client.py --agent codex lauf stand "Block 2 von 5 verschoben" --fortschritt 40
  py zentrale_client.py --agent codex lauf fertig "412 Dateien im Papierkorb, Protokoll liegt bei"   (--fehler, wenn es schiefging)
  py zentrale_client.py --agent codex laeufe                    (wer gerade woran arbeitet, was zuletzt fertig wurde)

Notizen (Markdown-Dateien):
  py zentrale_client.py --agent codex notizen
  py zentrale_client.py --agent codex notiz-neu "Inventur" --ordner Aufräumen --text-datei INVENTUR.md
  py zentrale_client.py --agent codex notiz-zeigen "Aufräumen/Inventur.md"
  py zentrale_client.py --agent codex notiz-ergaenzen "Besitzer/INDEX.md" --text "Mag kurze Antworten (Chat, 2.11.)"

Papierkorb (Seite „Papierkorb“; endgültig löschen darf nur der Besitzer):
  py zentrale_client.py --agent codex papierkorb
  py zentrale_client.py --agent codex notiz-suche "sicherung stick"

Finanzen (Seite „Finanzen“, Privat und Firma getrennt, alles mit --bereich firma auch für die Firma):
  py zentrale_client.py --agent claude finanzen                      (Überblick als Text)
  py zentrale_client.py --agent claude buchung "35 € Tanken"           („+1800 Lohn“ = Einnahme, ohne Vorzeichen = Ausgabe)
  py zentrale_client.py --agent claude buchungen --monat 2030-01
  py zentrale_client.py --agent claude finanz-import auszug.csv        (CSV sofort, PDF/Bild in den Eingang)
  py zentrale_client.py --agent claude finanz-eingang                  (PDFs und Bilder, die auf Auslesen warten)
  py zentrale_client.py --agent claude finanz-eingang-holen 3 --ziel f3.pdf
  py zentrale_client.py --agent claude buchungen-eintragen --datei buchungen.json --eingang 3
  py zentrale_client.py --agent claude vertrag-neu "Streaming" --betrag 13,99 --rhythmus monat --kuendbar-bis 2030-02-01
  py zentrale_client.py --agent claude sparziel "Urlaub" --ziel 1500 --stand 300
  py zentrale_client.py --agent claude rechnung "Werkstatt" --betrag 290 --faellig 2030-01-31 ; rechnung-bezahlt 1
  py zentrale_client.py --agent claude finanz-tipp "Streaming seit 2 Monaten ungenutzt, Kündigen spart 168 € im Jahr."
  py zentrale_client.py --agent claude fristen                        (Abos, die in den nächsten 30 Tagen kündbar sind)

Sonst:
  py zentrale_client.py --agent codex ich                      (wer bin ich für die Zentrale?)
  py zentrale_client.py --agent codex agenten

Aus Python:
  from zentrale_client import Zentrale
  z = Zentrale(agent="codex")                          # liest Adresse und Schlüssel wie oben
  z.post("/api/wuensche", {"titel": "…", "prio": "hoch"})
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(errors="replace")
except (AttributeError, ValueError):
    pass

PY = "py" if os.name == "nt" else "python3"
ORDNER = Path(os.environ.get("ZENTRALE_SCHLUESSEL_ORDNER") or Path.home() / ".config" / "zentrale-starter")


class Fehler(Exception):
    pass


def schluessel_finden(schluessel=None, agent=None):
    if schluessel:
        return schluessel.strip()
    if os.environ.get("ZENTRALE_SCHLUESSEL"):
        return os.environ["ZENTRALE_SCHLUESSEL"].strip()
    agent = agent or os.environ.get("ZENTRALE_AGENT")
    if agent:
        try:
            return (ORDNER / f"{agent}.key").read_text(encoding="utf-8-sig").strip()
        except OSError:
            raise Fehler(f"Kein Schlüssel für „{agent}“ in {ORDNER}. Anlegen mit: {PY} start.py agent-neu {agent}")
    dateien = sorted(ORDNER.glob("*.key")) if ORDNER.is_dir() else []
    if len(dateien) == 1:
        return dateien[0].read_text(encoding="utf-8-sig").strip()
    if not dateien:
        raise Fehler(f"Kein Schlüssel gefunden. Anlegen mit: {PY} start.py agent-neu <name>")
    raise Fehler("Mehrere Schlüssel da. Bitte --agent <name> angeben oder ZENTRALE_AGENT setzen.")


class Zentrale:
    def __init__(self, url=None, schluessel=None, agent=None):
        self.url = (url or os.environ.get("ZENTRALE_URL") or "http://127.0.0.1:8090").rstrip("/")
        self.schluessel = schluessel_finden(schluessel, agent)

    def _anfrage(self, pfad, daten=None, timeout=30):
        req = urllib.request.Request(self.url + pfad, method="POST" if daten is not None else "GET",
                                     data=json.dumps(daten).encode() if daten is not None else None,
                                     headers={"Authorization": "Bearer " + self.schluessel, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read()).get("fehler")
            except ValueError:
                msg = None
            raise Fehler(msg or f"HTTP {e.code}")
        except urllib.error.URLError as e:
            raise Fehler(f"Zentrale nicht erreichbar ({self.url}). Läuft `{PY} start.py`? ({e.reason})")

    def get(self, pfad, timeout=30):
        return self._anfrage(pfad, timeout=timeout)

    def post(self, pfad, daten):
        return self._anfrage(pfad, daten)

    # ---------- Finanzen. Beträge in Cent, Buchungen: Einnahme +, Ausgabe − ----------

    def finanzen(self, bereich="privat", monat=""):
        """Überblick: Kontostand, Monat, Verlauf, Kategorien, Verträge, Vorschläge, Ziele, offene Tipps."""
        return self.get(f"/api/finanzen?bereich={urllib.parse.quote(bereich)}&monat={urllib.parse.quote(monat or '')}")

    def finanz_get(self, pfad, **q):
        return self.get(f"/api/finanzen/{pfad}?" + urllib.parse.urlencode({k: v for k, v in q.items() if v not in (None, "")}))

    def finanz_post(self, pfad, body):
        return self._anfrage(f"/api/finanzen/{pfad}", body, timeout=120)

    def buchung(self, satz, bereich=None, datum=None, kategorie=None, konto="", notiz="", quelle=None):
        """Satz wie „35 € Tanken“ oder „+1800 Lohn“ buchen. Ohne Vorzeichen = Ausgabe."""
        return self.finanz_post("satz", {"text": satz, "bereich": bereich, "datum": datum, "kategorie": kategorie, "konto": konto, "notiz": notiz, "quelle": quelle})

    def finanz_datei(self, pfad, bereich="privat", konto=""):
        """CSV wird sofort eingelesen, PDF und Bilder landen im Finanz-Eingang."""
        import base64
        with open(pfad, "rb") as f:
            daten = base64.b64encode(f.read()).decode()
        return self.finanz_post("upload", {"name": os.path.basename(pfad), "daten": daten, "bereich": bereich, "konto": konto})

    def finanz_eingang_holen(self, nr, ziel):
        import shutil
        req = urllib.request.Request(f"{self.url}/api/finanzen/eingang/{nr}/datei", headers={"Authorization": "Bearer " + self.schluessel})
        with urllib.request.urlopen(req, timeout=120) as r, open(ziel, "wb") as f:
            shutil.copyfileobj(r, f, 1024 * 1024)
        return ziel


# ---------- Finanzen: Befehle für Agenten ----------

def _eur(c, plus=False):
    c = int(c or 0)
    return ("−" if c < 0 else "+" if plus and c > 0 else "") + f"{abs(c) // 100:,}".replace(",", ".") + f",{abs(c) % 100:02d} €"


FINANZ_BEFEHLE = ("finanzen", "buchung", "buchungen", "buchung-aendern", "finanz-import", "finanz-eingang", "finanz-eingang-holen", "finanz-eingang-erledigt",
                  "buchungen-eintragen", "vertraege", "vertrag-neu", "vertrag-aendern", "sparziele", "sparziel", "sparziel-stand", "kontostand",
                  "finanz-tipps", "finanz-tipp", "finanz-tipp-erledigt", "rechnungen", "rechnung", "rechnung-bezahlt", "fristen")


def finanz_parser(sub, gemeinsam):
    b = lambda p: p.add_argument("--bereich", default="privat", choices=["privat", "firma"])
    p = sub.add_parser("finanzen", help="Finanzen: Überblick als Text (Kontostand, Monat, Abos, Ziele, Tipps)", parents=[gemeinsam]); b(p)
    p.add_argument("--monat", default="", help="JJJJ-MM, Standard: dieser Monat")
    p = sub.add_parser("buchung", help="Satz wie „35 € Tanken“ oder „+1800 Lohn“ buchen (ohne Vorzeichen = Ausgabe)", parents=[gemeinsam])
    p.add_argument("satz"); p.add_argument("--bereich", choices=["privat", "firma"]); p.add_argument("--datum", help="JJJJ-MM-TT, Standard: heute")
    p.add_argument("--kategorie", help="z. B. auto, lebensmittel, abos (sonst automatisch)"); p.add_argument("--konto", default=""); p.add_argument("--notiz", default="")
    p.add_argument("--quelle", choices=["hand", "agent"])
    p = sub.add_parser("buchungen", help="Buchungen zeigen", parents=[gemeinsam]); b(p)
    p.add_argument("--monat", default=""); p.add_argument("--kategorie"); p.add_argument("--suche"); p.add_argument("--anzahl", type=int, default=50)
    p = sub.add_parser("buchung-aendern", help="Kategorie, Notiz, Bereich einer Buchung ändern oder entfernen", parents=[gemeinsam])
    p.add_argument("nr"); p.add_argument("--kategorie"); p.add_argument("--notiz"); p.add_argument("--bereich", choices=["privat", "firma"]); p.add_argument("--text")
    p.add_argument("--entfernen", action="store_true", help="ausblenden (wird nicht gelöscht)")
    p = sub.add_parser("finanz-import", help="Kontoauszug hochladen: CSV wird sofort eingelesen, PDF/Bild kommt in den Eingang", parents=[gemeinsam]); b(p)
    p.add_argument("datei"); p.add_argument("--konto", default="", help="Name des Kontos (sonst aus der Datei erraten)")
    p = sub.add_parser("finanz-eingang", help="PDFs und Bilder, die auf Auslesen warten", parents=[gemeinsam])
    p.add_argument("--alle", action="store_true", help="auch erledigte")
    p = sub.add_parser("finanz-eingang-holen", help="Datei aus dem Finanz-Eingang holen", parents=[gemeinsam])
    p.add_argument("nr"); p.add_argument("--ziel", required=True)
    p = sub.add_parser("finanz-eingang-erledigt", help="Eingang ohne Buchungen abschließen (z. B. kein Auszug)", parents=[gemeinsam])
    p.add_argument("nr"); p.add_argument("--ergebnis", default=""); p.add_argument("--zurueck", action="store_true")
    p = sub.add_parser("buchungen-eintragen", help="Buchungen aus einer JSON-Datei eintragen (aus PDF oder Bild gelesen)", parents=[gemeinsam])
    p.add_argument("--datei", required=True, help='[{"datum": "2026-10-21", "betrag": "-42,30", "text": "Billa", "gegenpartei": "Billa"}, …] oder {"buchungen": […], "kontostand": {…}}')
    p.add_argument("--eingang", help="Nummer im Finanz-Eingang (wird danach erledigt)"); p.add_argument("--bereich", choices=["privat", "firma"])
    p.add_argument("--konto", default=""); p.add_argument("--quelle", choices=["pdf", "bild", "agent"]); p.add_argument("--offen-lassen", action="store_true")
    p = sub.add_parser("vertraege", help="Verträge und Abos mit Monatssumme und erkannten Abos", parents=[gemeinsam]); b(p)
    p = sub.add_parser("vertrag-neu", aliases=["abo"], help="Vertrag oder Abo anlegen", parents=[gemeinsam]); b(p)
    p.add_argument("name"); p.add_argument("--betrag", required=True, help="Preis je Rhythmus, z. B. 13,99")
    p.add_argument("--rhythmus", default="monat", choices=["monat", "quartal", "jahr", "woche"]); p.add_argument("--kategorie")
    p.add_argument("--kuendbar-bis", help="JJJJ-MM-TT"); p.add_argument("--frist", default="", help="Kündigungsfrist, z. B. „1 Monat zum Monatsende“")
    p.add_argument("--naechste", help="nächste Zahlung JJJJ-MM-TT"); p.add_argument("--notiz", default=""); p.add_argument("--hinweis", default="", help="z. B. ungenutzt")
    p = sub.add_parser("vertrag-aendern", help="Vertrag ändern, kündigen (--status gekuendigt) oder als ungenutzt markieren", parents=[gemeinsam])
    p.add_argument("nr"); p.add_argument("--betrag"); p.add_argument("--rhythmus", choices=["monat", "quartal", "jahr", "woche"]); p.add_argument("--status", choices=["aktiv", "gekuendigt"])
    p.add_argument("--hinweis"); p.add_argument("--kuendbar-bis"); p.add_argument("--frist"); p.add_argument("--naechste"); p.add_argument("--notiz"); p.add_argument("--name")
    p.add_argument("--entfernen", action="store_true"); p.add_argument("--behalten", action="store_true", help="der Besitzer behält es: für diese Frist nicht mehr erinnern")
    p = sub.add_parser("fristen", help="Abos und Verträge, die in den nächsten 30 Tagen gekündigt werden müssten", parents=[gemeinsam])
    p = sub.add_parser("sparziele", help="Sparziele zeigen", parents=[gemeinsam]); b(p)
    p = sub.add_parser("sparziel", help="Sparziel anlegen", parents=[gemeinsam]); b(p)
    p.add_argument("name"); p.add_argument("--ziel", required=True, help="z. B. 5000"); p.add_argument("--stand", default="0"); p.add_argument("--bis")
    p = sub.add_parser("sparziel-stand", help="Stand eines Sparziels setzen (Betrag) oder ändern (--dazu)", parents=[gemeinsam])
    p.add_argument("nr"); p.add_argument("betrag", nargs="?"); p.add_argument("--dazu", help="dazulegen, negativ = wegnehmen")
    p = sub.add_parser("kontostand", help="Kontostand von Hand setzen", parents=[gemeinsam]); b(p)
    p.add_argument("betrag"); p.add_argument("--konto", default="Konto"); p.add_argument("--datum")
    p = sub.add_parser("finanz-tipps", help="offene Tipps des Beraters", parents=[gemeinsam])
    p.add_argument("--bereich", choices=["privat", "firma"]); p.add_argument("--alle", action="store_true")
    p = sub.add_parser("finanz-tipp", help="Tipp des Beraters an den Besitzer (erscheint auf der Seite Finanzen)", parents=[gemeinsam]); b(p)
    p.add_argument("text")
    p = sub.add_parser("finanz-tipp-erledigt", help="Tipp abhaken", parents=[gemeinsam])
    p.add_argument("id"); p.add_argument("--zurueck", action="store_true")
    p = sub.add_parser("rechnungen", help="offene Rechnungen (beim Lohn nachzahlen)", parents=[gemeinsam])
    p.add_argument("--alle", action="store_true", help="auch bezahlte")
    p = sub.add_parser("rechnung", help="offene Rechnung eintragen (gleiche Rechnungsnummer = ergänzen)", parents=[gemeinsam]); b(p)
    p.add_argument("name"); p.add_argument("--betrag", required=True); p.add_argument("--faellig", help="JJJJ-MM-TT"); p.add_argument("--rechnungsnr", default="")
    p.add_argument("--link", default="", help="Zahl-Link (https://…)"); p.add_argument("--notiz", default=""); p.add_argument("--nicht-bei-lohn", action="store_true")
    p = sub.add_parser("rechnung-bezahlt", help="Rechnung als bezahlt markieren", parents=[gemeinsam])
    p.add_argument("nr"); p.add_argument("--zurueck", action="store_true", help="wieder offen")


def rzeile(r):
    return (f"[Nr. {r['nr']}] {'BEZAHLT ' if r['status'] == 'bezahlt' else ''}{r['name']}: {_eur(r['betrag_cent'])}" + (f", fällig {r['faellig']}" if r.get("faellig") else "")
            + (" (ÜBERFÄLLIG)" if r.get("ueberfaellig") else "") + (f", Rechnung {r['rechnungsnr']}" if r.get("rechnungsnr") else "")
            + (f", Link {r['link']}" if r.get("link") else "")
            + (f", Dateien: {', '.join(r['dateien'])}" if r.get("dateien") else ""))


def finanz_ausfuehren(z, args):
    w = args.befehl
    zeile = lambda x: f"[Nr. {x['nr']}] {x['datum']}  {_eur(x['betrag_cent'], True):>13}  {x['emoji']} {x.get('gegenpartei') or x['text'][:60]}" + \
        (f" · {x['text'][:60]}" if x.get("gegenpartei") and x["gegenpartei"].lower() != x["text"].lower() else "") + (f"  [{x['bereich']}]" if x.get("bereich") == "firma" else "")
    vzeile = lambda v: f"[Nr. {v['nr']}] {v['emoji']} {v['name']}: {_eur(v['betrag_cent'])} je {v['rhythmus']} = {_eur(v['monat_cent'])}/Monat" + \
        (f", nächste {v['naechste']}" if v.get("naechste") else "") + (f", kündbar bis {v['kuendbar_bis']}" if v.get("kuendbar_bis") else "") + \
        (f"  ({v['hinweis']})" if v.get("hinweis") else "") + ("  GEKÜNDIGT" if v["status"] == "gekuendigt" else "")
    if w == "finanzen":
        u = z.finanzen(args.bereich, args.monat)
        W, K = u["werte"], u["kontostand"]
        print(f"Finanzen {u['bereich']}, {u['monat_name']}")
        print(f"Kontostand: {_eur(K['summe_cent'])}" + (" (" + ", ".join(f"{k['name']} {_eur(k['stand_cent'])} am {k['datum']}" for k in K["konten"]) + ")" if K["konten"] else " (noch nicht eingetragen)"))
        print(f"Einnahmen {_eur(W['einnahmen_cent'])}, Ausgaben {_eur(W['ausgaben_cent'])}, gespart {_eur(W['gespart_cent'])}" +
              (f" ({W['sparquote']} %)" if W["sparquote"] is not None else "") + (f", aufs Sparen gelegt {_eur(W['sparen_cent'])}" if W["sparen_cent"] else ""))
        print("Verlauf: " + " | ".join(f"{v['name'][:3]} {_eur(v['einnahmen_cent'], True)} {_eur(-v['ausgaben_cent'])}" for v in u["verlauf"]))
        if u["kategorien"]:
            print("Ausgaben nach Kategorie: " + ", ".join(f"{k['emoji']} {k['name']} {_eur(k['summe_cent'])}" for k in u["kategorien"]))
        print(f"Verträge und Abos: {_eur(u['vertraege_monat_cent'])} im Monat")
        for v in u["vertraege"]:
            print("  " + vzeile(v))
        for v in u["vorschlaege"]:
            print(f"  Erkannt (noch kein Vertrag): {v['name']} {_eur(v['betrag_cent'])} je {v['rhythmus']}, {v['monate']} Monate, zuletzt {v['letzte']}")
        for zl in u["ziele"]:
            print(f"Sparziel [Nr. {zl['nr']}] {zl['name']}: {_eur(zl['stand_cent'])} von {_eur(zl['ziel_cent'])}" + (f" bis {zl['bis']}" if zl.get("bis") else ""))
        for t in u["tipps"]:
            print(f"Tipp ({t['id']}): {t['text']}")
        for r in u.get("rechnungen") or []:
            print("Offene Rechnung " + rzeile(r))
        if u["eingang_wartet"]:
            print(f"Finanz-Eingang: {u['eingang_wartet']} {'Datei wartet' if u['eingang_wartet'] == 1 else 'Dateien warten'} auf Auslesen (finanz-eingang).")
        print(f"{u['buchungen_gesamt']} Buchungen" + (f" von {u['erste']} bis {u['letzte']}" if u["erste"] else ""))
    elif w == "buchung":
        x = z.buchung(args.satz, args.bereich, args.datum, args.kategorie, args.konto, args.notiz, args.quelle)
        print("Gebucht: " + zeile(x) + f"  ({x['kategorie_name']}, {x['bereich']})")
    elif w == "buchungen":
        d = z.finanz_get("buchungen", bereich=args.bereich, monat=args.monat, kategorie=args.kategorie, q=args.suche, anzahl=args.anzahl)
        for x in d["buchungen"]:
            print(zeile(x))
        print(f"{len(d['buchungen'])} von {d['anzahl']} Buchungen, Summe {_eur(sum(x['betrag_cent'] for x in d['buchungen']), True)}")
    elif w == "buchung-aendern":
        b = {k: v for k, v in (("kategorie", args.kategorie), ("notiz", args.notiz), ("bereich", args.bereich), ("text", args.text)) if v is not None}
        if args.entfernen:
            b["entfernen"] = True
        x = z.finanz_post(f"buchungen/{args.nr}", b)
        print(("Ausgeblendet: " if x.get("entfernt") else "Geändert: ") + zeile(x) + (f"  (dazu {x['mit_geaendert']} weitere dieser Gegenpartei)" if x.get("mit_geaendert") else ""))
    elif w == "finanz-import":
        r = z.finanz_datei(args.datei, args.bereich, args.konto)
        if r["art"] == "csv":
            e = r["ergebnis"]
            print(f"Eingelesen ({e['bank']}, {e['von']} bis {e['bis']}): {e['text']}." + (f" Kontostand {e['konto']}: {_eur(e['kontostand'])}." if e.get("kontostand") is not None else ""))
            for f in e["fehler"]:
                print("  " + f)
        else:
            print(f"Im Finanz-Eingang: Nr. {r['eingang']['nr']} ({r['art']})" + (", war schon da" if r.get("schon_da") else ", wartet auf Auslesen"))
    elif w == "finanz-eingang":
        for e in z.finanz_get("eingang", alle="1" if args.alle else "0")["eingang"]:
            print(f"[Nr. {e['nr']}] {e['status']}: {e['name']} ({e['art']}, {e['bereich']}, {e['bytes'] // 1024} kB, {time.strftime('%d.%m. %H:%M', time.localtime(e['zeit']))})" +
                  (f" → {e['ergebnis']}" if e.get("ergebnis") else ""))
    elif w == "finanz-eingang-holen":
        print("Gespeichert:", z.finanz_eingang_holen(args.nr, args.ziel))
    elif w == "finanz-eingang-erledigt":
        e = z.finanz_post(f"eingang/{args.nr}", {"status": "wartet" if args.zurueck else "erledigt", "ergebnis": args.ergebnis})
        print(f"Eingang Nr. {e['nr']}: {e['status']}")
    elif w == "buchungen-eintragen":
        with open(args.datei, encoding="utf-8") as f:
            d = json.load(f)
        body = d if isinstance(d, dict) else {"buchungen": d}
        for k, v in (("eingang", args.eingang), ("bereich", args.bereich), ("konto", args.konto), ("quelle", args.quelle)):
            if v:
                body[k] = v
        body["erledigt"] = not args.offen_lassen
        r = z.finanz_post("buchungen/menge", body)
        print(f"{r['neu']} neu, {r['doppelt']} doppelt, {r['zusammengefuehrt']} zusammengeführt" + (f", Eingang Nr. {args.eingang} erledigt" if args.eingang and not args.offen_lassen else ""))
        for f in r["fehler"]:
            print("  " + f)
    elif w == "vertraege":
        u = z.finanzen(args.bereich)
        print(f"Verträge und Abos ({u['bereich']}): {_eur(u['vertraege_monat_cent'])} im Monat")
        for v in u["vertraege"]:
            print(vzeile(v))
        for v in u["vorschlaege"]:
            print(f"Erkannt, noch nicht eingetragen: {v['name']} {_eur(v['betrag_cent'])} je {v['rhythmus']} ({v['monate']} Monate, zuletzt {v['letzte']}), Schlüssel „{v['schluessel']}“")
    elif w in ("vertrag-neu", "abo"):
        v = z.finanz_post("vertraege", {"bereich": args.bereich, "name": args.name, "betrag": args.betrag, "rhythmus": args.rhythmus, "kategorie": args.kategorie,
                                        "kuendbar_bis": args.kuendbar_bis or "", "kuendigungsfrist": args.frist, "naechste_zahlung": args.naechste or "",
                                        "notiz": args.notiz, "hinweis": args.hinweis})
        print("Angelegt: " + vzeile(v))
    elif w == "vertrag-aendern":
        b = {k: v for k, v in (("betrag", args.betrag), ("rhythmus", args.rhythmus), ("status", args.status), ("hinweis", args.hinweis), ("kuendbar_bis", args.kuendbar_bis),
                               ("kuendigungsfrist", args.frist), ("naechste_zahlung", args.naechste), ("notiz", args.notiz), ("name", args.name)) if v is not None}
        if args.entfernen:
            b["entfernen"] = True
        if args.behalten:
            b["behalten"] = True
        print("Geändert: " + vzeile(z.finanz_post(f"vertraege/{args.nr}", b)))
    elif w == "fristen":
        F = z.finanz_get("fristen")["fristen"]
        print("Keine Kündigungsfristen in den nächsten 30 Tagen." if not F else "\n".join(
            f"[Nr. {v['nr']}] {v['name']}: kündbar bis {v['kuendbar_bis']} (in {v['tage']} Tagen), {_eur(v['betrag_cent'])} je {v['rhythmus']}"
            + (f", Testphase bis {v['testphase_bis']}" if v.get("testphase_bis") else "") for v in F))
    elif w == "sparziele":
        for zl in z.finanzen(args.bereich)["ziele"]:
            print(f"[Nr. {zl['nr']}] {zl['name']}: {_eur(zl['stand_cent'])} von {_eur(zl['ziel_cent'])} ({round(100 * zl['stand_cent'] / zl['ziel_cent'])} %)" + (f", bis {zl['bis']}" if zl.get("bis") else ""))
    elif w == "sparziel":
        zl = z.finanz_post("ziele", {"bereich": args.bereich, "name": args.name, "ziel": args.ziel, "stand": args.stand, "bis": args.bis or ""})
        print(f"Sparziel Nr. {zl['nr']} angelegt: {zl['name']}, {_eur(zl['stand_cent'])} von {_eur(zl['ziel_cent'])}")
    elif w == "sparziel-stand":
        if not args.betrag and not args.dazu:
            raise SystemExit("Betrag oder --dazu angeben.")
        zl = z.finanz_post(f"ziele/{args.nr}", {"stand": args.betrag} if args.betrag else {"dazu": args.dazu})
        print(f"{zl['name']}: {_eur(zl['stand_cent'])} von {_eur(zl['ziel_cent'])}")
    elif w == "kontostand":
        k = z.finanz_post("konto", {"bereich": args.bereich, "name": args.konto, "stand": args.betrag, "datum": args.datum})
        print(f"Kontostand {k['name']} ({k['bereich']}): {_eur(k['stand_cent'])} am {k['datum']}")
    elif w == "finanz-tipps":
        for t in z.finanz_get("tipps", bereich=args.bereich, alle="1" if args.alle else "")["tipps"]:
            print(f"[{t['id']}] {'erledigt ' if t['erledigt'] else ''}({t['bereich']}, {t['art']}) {t['text']}")
    elif w == "finanz-tipp":
        t = z.finanz_post("tipps", {"bereich": args.bereich, "text": args.text})
        print(f"Tipp Nr. {t['nr']} eingetragen (id {t['id']}).")
    elif w == "finanz-tipp-erledigt":
        z.finanz_post(f"tipps/{args.id}", {"erledigt": not args.zurueck})
        print("Zurückgeholt." if args.zurueck else "Abgehakt.")
    elif w == "rechnungen":
        R = z.finanz_get("rechnungen", alle="1" if args.alle else "")["rechnungen"]
        for r in R:
            print(rzeile(r))
        print(f"{sum(1 for r in R if r['status'] == 'offen')} offen, zusammen {_eur(sum(r['betrag_cent'] for r in R if r['status'] == 'offen'))}")
    elif w == "rechnung":
        b = {k: v for k, v in (("bereich", args.bereich), ("name", args.name), ("betrag", args.betrag), ("faellig", args.faellig), ("rechnungsnr", args.rechnungsnr),
                               ("link", args.link), ("notiz", args.notiz)) if v}
        b["bei_lohn"] = not args.nicht_bei_lohn
        r = z.finanz_post("rechnungen", b)
        print("Eingetragen: " + rzeile(r))
    elif w == "rechnung-bezahlt":
        print(rzeile(z.finanz_post(f"rechnungen/{args.nr}", {"bezahlt": not args.zurueck})))


def zeit(t):
    return time.strftime("%d.%m.%Y %H:%M", time.localtime(t)) if t else ""


def text_aus(args):
    if getattr(args, "text_datei", None):
        return Path(args.text_datei).read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    return getattr(args, "text", None) or ""


class FrageDazu(argparse.Action):
    def __call__(self, parser, ns, wert, option=None):
        ns.fragen = (ns.fragen or []) + [{"text": wert, "vorschlaege": []}]


class VorschlaegeDazu(argparse.Action):
    def __call__(self, parser, ns, wert, option=None):
        if not ns.fragen:
            parser.error("--vorschlaege gehört hinter eine --frage")
        ns.fragen[-1]["vorschlaege"] = [v.strip() for v in wert.split("|") if v.strip()]


def groesse(b):
    for e in ("Byte", "KB", "MB", "GB"):
        if b < 1024 or e == "GB":
            return f"{b:.0f} {e}" if e == "Byte" else f"{b:.1f} {e}".replace(".", ",")
        b /= 1024


FASSUNG = "2026-11-02"   # gleich wie hub.FASSUNG; weicht die laufende Zentrale ab, kommt eine Warnung


def pruefen(z):
    """Warnt, wenn die laufende Zentrale älter ist oder aus einem anderen Ordner kommt als dieser Client.
    Dann arbeitet der Agent sonst an der falschen (alten) Zentrale weiter.
    Warnt auch, wenn REGELN.md nicht (oder alt) in der Anleitung von Claude Code oder Codex steht."""
    hier = Path(__file__).resolve().parent
    w = []
    try:
        from regeln_verteilen import veraltet
        alt = veraltet()
    except Exception:   # fehlt das Skript oder klemmt eine Datei, soll der Client trotzdem gehen
        alt = []
    if alt:
        w.append("Die Regeln fehlen oder sind alt in " + ", ".join(str(p) for p in alt) + ". Dann gelten sie nicht in "
                 f"jedem Projekt: `{PY} \"{hier / 'regeln_verteilen.py'}\"` aufrufen, danach einen neuen Thread starten.")
    try:
        d = z.get("/api/ich", timeout=3)
    except Fehler:
        d = {"fassung": FASSUNG}   # Zentrale nicht erreichbar: dazu meldet sich der eigentliche Befehl selbst
    if d.get("fassung") != FASSUNG:
        w.append(f"Die laufende Zentrale hat Fassung {d.get('fassung') or 'alt (ohne Fassung)'}, dieser Ordner {FASSUNG}. "
                 f"Sie wurde nach dem Update nicht neu gestartet: `{PY} start.py` beenden und neu starten.")
    if d.get("ordner") and Path(d["ordner"]).resolve() != hier:
        w.append(f"Die laufende Zentrale kommt aus {d['ordner']}, nicht aus {hier}. Es darf nur eine Zentrale geben: "
                 "die aus diesem Ordner. Nicht an der anderen weiterarbeiten, den Besitzer fragen (AGENTS.md, „Nur eine Zentrale“).")
    for x in w:
        print("ACHTUNG: " + x, file=sys.stderr)


def wunsch_zeile(w):
    prio = f"[{w['prio']}] " if w.get("prio") else ""
    gruppe = f"  ({w['gruppe']})" if w.get("gruppe") else ""
    return f"Wunsch Nr. {w['nr']}  {prio}{w['titel']}{gruppe}"


def ausfuehren(z, a):
    q = urllib.request.quote
    if a.befehl == "ich":
        d = z.get("/api/ich")
        print(d["id"] + (f"  (Zentrale Fassung {d['fassung']}, Ordner {d['ordner']})" if d.get("fassung") else ""))
    elif a.befehl == "agenten":
        for x in z.get("/api/agenten")["agenten"]:
            print(f"{x['id']:<20} zuletzt: {zeit(x['zuletzt']) or 'noch nie'}")

    elif a.befehl == "wuensche":
        d = z.get("/api/wuensche")
        print(f"Offen ({len(d['offen'])}):")
        for w in d["offen"]:
            print("  " + wunsch_zeile(w))
        if a.alle:
            print(f"Erledigt ({len(d['erledigt'])}):")
            for w in d["erledigt"]:
                print(f"  {wunsch_zeile(w)}  → {w.get('ergebnis') or w['status']}")
    elif a.befehl == "wunsch":
        w = z.post("/api/wuensche", {"titel": a.titel, "text": a.text or "", "gruppe": a.gruppe or "", "prio": a.prio})
        print(f"Eingetragen: Wunsch Nr. {w['nr']}")
    elif a.befehl == "wunsch-zeigen":
        w = z.get(f"/api/wuensche/{q(a.nr)}")
        print(wunsch_zeile(w), f"· {w['status']}")
        if w["text"]:
            print("\n" + w["text"])
        if w.get("ergebnis"):
            print(f"\nErgebnis: {w['ergebnis']}")
        for n in w["notizen"]:
            print(f"\n{zeit(n['zeit'])} {n['von']}: {n['text']}")
    elif a.befehl == "wunsch-notiz":
        w = z.post(f"/api/wuensche/{q(a.nr)}/notizen", {"text": a.text})
        print(f"Notiz an Wunsch Nr. {w['nr']} gehängt.")
    elif a.befehl == "wunsch-erledigt":
        w = z.post(f"/api/wuensche/{q(a.nr)}", {"status": "erledigt", "ergebnis": a.ergebnis})
        print(f"Wunsch Nr. {w['nr']} abgehakt.")
    elif a.befehl == "wunsch-verwerfen":
        w = z.post(f"/api/wuensche/{q(a.nr)}", {"status": "verworfen", "ergebnis": a.grund})
        print(f"Wunsch Nr. {w['nr']} verworfen.")
    elif a.befehl == "wunsch-prio":
        w = z.post(f"/api/wuensche/{q(a.nr)}", {"prio": a.prio})
        print(f"Wunsch Nr. {w['nr']}: Priorität {w['prio']}.")

    elif a.befehl == "lauf":
        feld = {"start": "titel", "stand": "schritt", "fertig": "ergebnis"}[a.aktion]
        d = {"aktion": a.aktion, "lauf": a.lauf, feld: a.text or "", "wunsch": a.wunsch or "", "quelle": "hand"}
        if a.fortschritt is not None:
            d["fortschritt"] = a.fortschritt
        if a.fehler:
            d["fehler"] = True
        x = z.post("/api/laeufe", d)
        print(f"Lauf {x['lauf']}: {a.aktion}" + (f" · Wunsch Nr. {x['wunsch']}" if x.get("wunsch") else "") + (f" · {x['titel']}" if x.get("titel") else ""))
    elif a.befehl == "laeufe":
        d = z.get("/api/laeufe")
        print(f"Gerade dran ({len(d['aktiv'])}):")
        for x in d["aktiv"]:
            print(f"  {x['agent']}: " + (f"Wunsch Nr. {x['wunsch']} · " if x.get("wunsch") else "") + (x.get("titel") or x["lauf"])
                  + f"  seit {zeit(x['start'])}" + (f" · {x['schritt']}" if x.get("schritt") else "") + ("  (still)" if x.get("still") else ""))
        print("Zuletzt fertig:")
        for x in d["fertig"][:a.anzahl]:
            print(f"  {zeit(x['ende'])} {x['agent']} [{x['status']}] " + (f"Wunsch Nr. {x['wunsch']} · " if x.get("wunsch") else "")
                  + (x.get("titel") or x["lauf"]) + (f" → {x['ergebnis'][:120]}" if x.get("ergebnis") else ""))

    elif a.befehl == "projekte":
        d = z.get("/api/pos")
        offen = {}
        for x in d["aufgaben"]:
            if not x["erledigt"]:
                offen.setdefault(x["projekt"], []).append(x)
        for p in sorted(d["projekte"], key=lambda p: (["aktiv", "ruht", "archiv"].index(p["status"]), p["name"].lower())):
            schritt = f"  als Nächstes: {p['naechster_schritt']}" if p.get("naechster_schritt") else ""
            print(f"[{p['status']}] {p['name']}  ({len(offen.get(p['id'], []))} offen){schritt}")
            for x in offen.get(p["id"], []):
                print(f"    - {x['titel']}  (id {x['id']}, für {x['fuer']}{', fällig ' + x['faellig'] if x.get('faellig') else ''})")
        if offen.get(None):
            print("[ohne Projekt]")
            for x in offen[None]:
                print(f"    - {x['titel']}  (id {x['id']}, für {x['fuer']})")
    elif a.befehl == "projekt-neu":
        orte = []
        for o in a.ort or []:
            g, _, p = o.partition(":")
            orte.append({"geraet": g if p else "", "pfad": p or g})
        p = z.post("/api/pos/projekte", {"name": a.name, "beschreibung": a.beschreibung or "", "orte": orte, "repos": a.repo or [],
                                         "naechster_schritt": a.schritt or "", "status": a.status})
        print(f"Projekt „{p['name']}“ angelegt (id {p['id']}).")
    elif a.befehl == "projekt-schritt":
        p = z.post(f"/api/pos/projekte/{q(a.projekt)}", {"naechster_schritt": a.text})
        print(f"{p['name']}: als Nächstes „{p['naechster_schritt']}“.")
    elif a.befehl == "projekt-status":
        p = z.post(f"/api/pos/projekte/{q(a.projekt)}", {"status": a.status})
        print(f"{p['name']}: {p['status']}.")
    elif a.befehl == "aufgabe":
        x = z.post("/api/pos/aufgaben", {"titel": a.titel, "projekt": a.projekt or "", "faellig": a.faellig or "", "fuer": a.fuer or "",
                                         "wunsch": a.wunsch or "", "notiz": a.notiz or ""})
        print(f"Aufgabe angelegt (id {x['id']}).")
    elif a.befehl == "aufgabe-erledigt":
        x = z.post(f"/api/pos/aufgaben/{q(a.id)}", {"erledigt": not a.zurueck})
        print(f"„{x['titel']}“ {'wieder offen' if a.zurueck else 'abgehakt'}.")

    elif a.befehl == "berichte":
        for b in z.get("/api/berichte")["berichte"][:a.anzahl]:
            offen = sum(1 for f in b["fragen"] if not f.get("antwort"))
            neu = sum(1 for m in b["verlauf"] if m["von"] == "besitzer" and not m.get("abgeholt"))
            zusatz = ", ".join(t for t in (f"{offen} {'Frage' if offen == 1 else 'Fragen'} offen" if offen else "", f"{neu} {'neue Antwort' if neu == 1 else 'neue Antworten'}" if neu else "") if t)
            print(f"Bericht Nr. {b['nr']}  {b['titel']}  ({b['von']}, {zeit(b['zeit'])}){'  · ' + zusatz if zusatz else ''}")
    elif a.befehl == "bericht":
        b = z.get(f"/api/berichte/{q(a.nr)}")
        print(f"Bericht Nr. {b['nr']}: {b['titel']}  ({b['von']}, {zeit(b['zeit'])})")
        if b["kurz"]:
            print("\n" + b["kurz"])
        for i, f in enumerate(b["fragen"], 1):
            ant = f["antwort"]["text"] if f.get("antwort") else "(offen)"
            print(f"\nFrage {i}: {f['text']}\n  Antwort: {ant}")
        for m in b["verlauf"]:
            if not m.get("frage"):
                print(f"\n{zeit(m['zeit'])} {m['von']}: {m['text']}")
    elif a.befehl == "bericht-neu":
        b = z.post("/api/berichte", {"titel": a.titel, "kurz": a.kurz or "", "text": text_aus(a), "fragen": a.fragen or [],
                                     "sitzung": a.sitzung or "", "projekt": a.projekt or "", "wunsch": a.wunsch or ""})
        print(f"Bericht Nr. {b['nr']} angelegt, {len(b['fragen'])} {'Frage' if len(b['fragen']) == 1 else 'Fragen'}.")
        if not b["fragen"] and "?" in (b.get("kurz") or "") + (b.get("text") or ""):
            print("Hinweis: Der Bericht hat keine Frage zum Antippen. Fragen an den Besitzer gehören je in ein eigenes --frage, "
                  "dann bekommt er sie nacheinander.")
    elif a.befehl == "bericht-antwort":
        b = z.post(f"/api/berichte/{q(a.nr)}/nachricht", {"text": a.text})
        print(f"Antwort in Bericht Nr. {b['nr']} geschrieben.")
    elif a.befehl == "bericht-erledigt":
        b = z.post(f"/api/berichte/{q(a.nr)}/erledigt", {"antworten": a.antwort or [], "notiz": a.notiz or ""})
        print(f"Bericht Nr. {b['nr']} geschlossen.")
    elif a.befehl == "berichte-warten":
        pfad = f"/api/berichte/warten?sekunden={a.max}" + (f"&sitzung={q(a.sitzung)}" if a.sitzung else "")
        d = z.get(pfad, timeout=a.max + 30)
        if not d["neu"]:
            print("Keine neue Nachricht.")
            sys.exit(3)
        je = {}
        for m in d["neu"]:
            print(f"Bericht Nr. {m['nr']} ({m['titel']}){' · ' + m['frage'] if m['frage'] else ''}\n  Besitzer: {m['text']}")
            je.setdefault(m["bericht"], []).append(m["nachricht"])
        for bid, ids in je.items():
            z.post(f"/api/berichte/{bid}/abgeholt", {"nachrichten": ids})

    elif a.befehl == "notizen":
        for n in z.get("/api/notizen")["notizen"][:a.anzahl]:
            print(f"{n['pfad']}  ({n['titel']}, {zeit(n['zeit'])})")
    elif a.befehl == "notiz-neu":
        n = z.post("/api/notizen/neu", {"ordner": a.ordner or "", "titel": a.titel, "text": text_aus(a)})
        print(f"Notiz angelegt: {n['pfad']}")
    elif a.befehl == "notiz-ergaenzen":
        n = z.get(f"/api/notizen/notiz?pfad={q(a.pfad)}")
        zusatz = text_aus(a).strip()
        if not zusatz:
            raise Fehler("Text fehlt (--text oder --text-datei).")
        text = n["text"].rstrip("\n") + f"\n\n## {time.strftime('%d.%m.%Y')} ({a.agent or 'Agent'})\n\n{zusatz}\n"
        z.post("/api/notizen/speichern", {"pfad": n["pfad"], "text": text, "version": n["version"]})
        print(f"Notiz ergänzt: {n['pfad']}")
    elif a.befehl == "papierkorb":
        d = z.get("/api/papierkorb")
        print(f"Im Papierkorb: {len(d['eintraege'])} aus dem Aufräumen, {len(d['notizen'])} Notizen, zusammen {groesse(d['bytes'])}")
        for e in d["eintraege"]:
            print(f"  Schritt {e['nr']}: {e['name']}  ({groesse(e['bytes'])}, {e['zeit'][:10]})  aus {e['von']}" + ("" if e["da"] else "  [fehlt]"))
        for n in d["notizen"]:
            print(f"  Notiz {n['pfad']}")
        print(f"Zurücklegen: {PY} aufraeumen{os.sep}rueckgaengig.py <Schritt>. Endgültig löschen darf nur der Besitzer (Seite Papierkorb).")
    elif a.befehl == "notiz-zeigen":
        print(z.get(f"/api/notizen/notiz?pfad={q(a.pfad)}")["text"])
    elif a.befehl == "notiz-suche":
        for t in z.get(f"/api/notizen/suche?q={q(a.suche)}")["treffer"]:
            print(f"{t['pfad']}\n  {t['ausschnitt']}")


def main():
    def optionen(standard):
        g = argparse.ArgumentParser(add_help=False, argument_default=standard)
        g.add_argument("--url", help="Adresse der Zentrale (Standard http://127.0.0.1:8090)")
        g.add_argument("--schluessel", help="Schlüssel direkt (besser: --agent oder Schlüsseldatei)")
        g.add_argument("--agent", help="Name des Agenten, dessen Schlüsseldatei benutzt wird")
        return g
    # Die Optionen gehen vor und nach dem Befehl; SUPPRESS verhindert, dass der Befehl sie mit None überschreibt
    gemeinsam = optionen(argparse.SUPPRESS)
    ap = argparse.ArgumentParser(description="Anschluss an die Zentrale für Agenten.", parents=[optionen(None)],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    sub = ap.add_subparsers(dest="befehl", required=True)
    P = lambda name, hilfe: sub.add_parser(name, help=hilfe, parents=[gemeinsam])

    P("ich", "eigene Agenten-ID zeigen")
    P("agenten", "alle Agenten mit letztem Kontakt")

    p = P("wuensche", "offene Wünsche zeigen"); p.add_argument("--alle", action="store_true", help="auch Erledigtes")
    p = P("wunsch", "neuen Wunsch des Besitzers eintragen (immer mit Priorität)")
    p.add_argument("titel"); p.add_argument("--text"); p.add_argument("--gruppe")
    p.add_argument("--prio", required=True, choices=["hoch", "mittel", "niedrig"])
    p = P("wunsch-zeigen", "Wunsch mit Text und Notizen"); p.add_argument("nr")
    p = P("wunsch-notiz", "Notiz (Stand) an einen Wunsch hängen"); p.add_argument("nr"); p.add_argument("text")
    p = P("wunsch-erledigt", "Wunsch abhaken"); p.add_argument("nr"); p.add_argument("--ergebnis", required=True)
    p = P("wunsch-verwerfen", "Wunsch verwerfen"); p.add_argument("nr"); p.add_argument("--grund", required=True)
    p = P("wunsch-prio", "Priorität ändern"); p.add_argument("nr"); p.add_argument("prio", choices=["hoch", "mittel", "niedrig"])

    p = P("lauf", "melden, woran du gerade arbeitest (Start, Zwischenstand, Fertig)")
    p.add_argument("aktion", choices=["start", "stand", "fertig"]); p.add_argument("text", nargs="?", help="Titel, Schritt oder Ergebnis")
    p.add_argument("--wunsch"); p.add_argument("--fortschritt", type=int, help="0 bis 100")
    p.add_argument("--fehler", action="store_true"); p.add_argument("--lauf", default="haupt", help="eigene Kennung, wenn mehrere Arbeiten gleichzeitig laufen")
    p = P("laeufe", "wer gerade woran arbeitet, was zuletzt fertig wurde"); p.add_argument("--anzahl", type=int, default=10)

    P("projekte", "Projekte mit offenen Aufgaben")
    p = P("projekt-neu", "Projekt anlegen"); p.add_argument("name"); p.add_argument("--beschreibung"); p.add_argument("--schritt")
    p.add_argument("--ort", action="append", help="Gerät:Pfad, mehrfach möglich"); p.add_argument("--repo", action="append")
    p.add_argument("--status", default="aktiv", choices=["aktiv", "ruht", "archiv"])
    p = P("projekt-schritt", "„Als Nächstes“ eines Projekts setzen"); p.add_argument("projekt"); p.add_argument("text")
    p = P("projekt-status", "Status eines Projekts setzen"); p.add_argument("projekt"); p.add_argument("status", choices=["aktiv", "ruht", "archiv"])
    p = P("aufgabe", "neue Aufgabe"); p.add_argument("titel"); p.add_argument("--projekt"); p.add_argument("--faellig", help="JJJJ-MM-TT")
    p.add_argument("--fuer", help="besitzer oder ein Agent (Standard: du selbst)"); p.add_argument("--wunsch"); p.add_argument("--notiz")
    p = P("aufgabe-erledigt", "Aufgabe abhaken"); p.add_argument("id"); p.add_argument("--zurueck", action="store_true", help="wieder öffnen")

    p = P("berichte", "Berichte zeigen"); p.add_argument("--anzahl", type=int, default=20)
    p = P("bericht", "ein Bericht mit Verlauf"); p.add_argument("nr")
    p = P("bericht-neu", "Bericht mit Fragen an den Besitzer"); p.add_argument("titel"); p.add_argument("--kurz")
    p.add_argument("--text"); p.add_argument("--text-datei"); p.add_argument("--sitzung"); p.add_argument("--projekt"); p.add_argument("--wunsch")
    p.add_argument("--frage", action=FrageDazu, dest="fragen_dummy", help="Frage, mehrfach möglich")
    p.add_argument("--vorschlaege", action=VorschlaegeDazu, dest="vorschlaege_dummy", help="Vorschläge zur letzten Frage, getrennt mit |")
    p.set_defaults(fragen=None)
    p = P("bericht-antwort", "im Bericht antworten"); p.add_argument("nr"); p.add_argument("text")
    p = P("bericht-erledigt", "offene Fragen schließen (im Chat beantwortet)"); p.add_argument("nr")
    p.add_argument("--antwort", action="append"); p.add_argument("--notiz")
    p = P("berichte-warten", "warten, bis der Besitzer antwortet"); p.add_argument("--sitzung"); p.add_argument("--max", type=int, default=600)

    p = P("notizen", "Notizen zeigen"); p.add_argument("--anzahl", type=int, default=50)
    p = P("notiz-neu", "Notiz anlegen"); p.add_argument("titel"); p.add_argument("--ordner"); p.add_argument("--text"); p.add_argument("--text-datei")
    p = P("notiz-ergaenzen", "Text unten an eine Notiz anhängen (mit Datum)"); p.add_argument("pfad"); p.add_argument("--text"); p.add_argument("--text-datei")
    p = P("notiz-zeigen", "Notiz lesen"); p.add_argument("pfad")
    P("papierkorb", "was im Papierkorb liegt (Aufräumen und Notizen)")
    p = P("notiz-suche", "Notizen durchsuchen"); p.add_argument("suche")

    finanz_parser(sub, gemeinsam)

    a = ap.parse_args()
    try:
        z = Zentrale(a.url, a.schluessel, a.agent)
        pruefen(z)
        finanz_ausfuehren(z, a) if a.befehl in FINANZ_BEFEHLE or a.befehl == "abo" else ausfuehren(z, a)
    except Fehler as e:
        sys.exit(f"Fehler: {e}")


if __name__ == "__main__":
    # Windows: bei Weiterleitung (Agenten lesen die Ausgabe) nimmt Python sonst cp1252, und „→“ oder Umlaute brechen ab
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    main()
