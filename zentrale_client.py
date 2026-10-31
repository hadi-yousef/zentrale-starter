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


FASSUNG = "2026-11-01"   # gleich wie hub.FASSUNG; weicht die laufende Zentrale ab, kommt eine Warnung


def pruefen(z):
    """Warnt, wenn die laufende Zentrale älter ist oder aus einem anderen Ordner kommt als dieser Client.
    Dann arbeitet der Agent sonst an der falschen (alten) Zentrale weiter."""
    try:
        d = z.get("/api/ich", timeout=3)
    except Fehler:
        return
    hier = Path(__file__).resolve().parent
    w = []
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

    a = ap.parse_args()
    try:
        z = Zentrale(a.url, a.schluessel, a.agent)
        pruefen(z)
        ausfuehren(z, a)
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
