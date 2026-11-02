"""Zentrale: Webserver und Schnittstelle. Nur Python-Standardbibliothek.

Läuft standardmäßig nur auf diesem Rechner (127.0.0.1). Alles unter /api/ braucht einen Schlüssel
(Authorization: Bearer …), außer /api/lebt. Die Seite selbst (index.html) enthält keine Daten.
Start über ../start.py.
"""
import ipaddress
import json
import os
import socket
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import berichte
import finanzen
import geraete
import hub
import laeufe
import notizen
import papierkorb
import pos
import wuensche

HIER = Path(__file__).resolve().parent
SEITE = HIER / "index.html"
MELDER = HIER.parent / "melder" / "melder.py"   # frei abrufbar (kein Schlüssel, keine Daten), damit ein Gerät ihn holen kann
API_OFFEN = {"/api/lebt"}
GROSS = 600 * 1024   # Berichte und Notizen dürfen größer sein als andere Anfragen
# Nur eigene Namen annehmen (Schutz vor DNS-Rebinding): Eine fremde Webseite im Browser schickt ihren eigenen Namen als Host.
EIGENE_NAMEN = {"localhost"} | {n.strip().lower() for n in os.environ.get("ZENTRALE_HOSTS", "").split(",") if n.strip()}
# Mit --heimnetz: dieser Rechner und Tailscale. Tailscale verschlüsselt selbst, über normales HTTP im Heimnetz wären Schlüssel
# und private Daten mitlesbar. Das normale Heimnetz nur mit dem ausdrücklichen Schalter --lan-unverschluesselt.
TAILSCALE = (ipaddress.ip_network("100.64.0.0/10"), ipaddress.ip_network("fd7a:115c:a1e0::/48"))
NUR_TAILSCALE = ("Diese Zentrale nimmt von anderen Geräten nur verschlüsselte Verbindungen über Tailscale an. Über das normale "
                 "Heimnetz wären Schlüssel und Daten mitlesbar. Bitte die Tailscale-Adresse nehmen (docs/HOMELAB.md, Schritt 2).")


def absender_ok(ip):
    if not hub.HEIMNETZ:
        return True
    try:
        a = ipaddress.ip_address(ip)
        a = a.ipv4_mapped or a if a.version == 6 else a
        if a.is_loopback or any(a in n for n in TAILSCALE):
            return True
        heimnetz = not a.is_global and not a.is_multicast and not a.is_unspecified   # nicht aus dem Internet erreichbar
        if heimnetz and not hub.LAN_OFFEN:   # die Seite „Geräte“ zeigt, wer noch auf Tailscale umziehen muss
            if len(hub.ABGEWIESEN) >= 50:
                hub.ABGEWIESEN.clear()
            hub.ABGEWIESEN[str(a)] = int(time.time())
        return heimnetz and hub.LAN_OFFEN
    except ValueError:
        return False


def host_ok(host):
    if not host:
        return True
    name = host.strip().lower().rstrip(".")
    if name.startswith("["):
        name = name[1:].split("]")[0]
    elif name.count(":") == 1:
        name = name.rsplit(":", 1)[0].rstrip(".")
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        return name in EIGENE_NAMEN


class Handler(BaseHTTPRequestHandler):
    timeout = 60
    server_version = "Zentrale"
    sys_version = ""

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                         "script-src 'self' 'unsafe-inline'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def _vorab(self):
        """Host prüfen und Schlüssel lesen. Gibt (url, aid) zurück oder None, wenn schon geantwortet wurde."""
        url = urlsplit(self.path)
        if not absender_ok(self.client_address[0]):
            self._send(403, NUR_TAILSCALE.encode("utf-8"), "text/plain; charset=utf-8")
            return None
        if not host_ok(self.headers.get("Host")):
            self._json(403, {"fehler": "Unbekannte Adresse."})
            return None
        aid = hub.who(self.headers.get("Authorization"))
        if url.path.startswith("/api/") and url.path not in API_OFFEN and not aid:
            self._json(401, {"fehler": "Schlüssel fehlt oder ist falsch."})
            return None
        # Ein Geräte-Schlüssel darf nur melden (und fragen, wer er ist), sonst nichts
        if geraete.ist_geraet(aid) and url.path.startswith("/api/") and url.path not in API_OFFEN | {"/api/ich", "/api/geraete/melden"}:
            self._json(403, {"fehler": "Geräte-Schlüssel dürfen nur melden."})
            return None
        return url, aid

    def do_GET(self):
        v = self._vorab()
        if not v:
            return
        url, aid = v
        q = parse_qs(url.query)
        arg = lambda k, d="": (q.get(k) or [d])[0]
        teile = url.path.split("/")[3:]
        try:
            if url.path == "/api/lebt":
                # ohne Schlüssel: Fassung und Kennung des Ordners (Prüfsumme, kein Pfad), damit einrichten.py alte Zentralen erkennt
                return self._json(200, {"ok": True, "zentrale": "starter", "fassung": hub.FASSUNG, "ordner_id": hub.ORDNER_ID})
            if url.path == "/api/ich":
                return self._json(200, {"id": aid, "besitzer": aid == hub.BESITZER, "fassung": hub.FASSUNG, "ordner": str(hub.ORDNER)})
            if url.path == "/api/geraete":
                return self._json(200, geraete.liste())
            if url.path == "/api/agenten":
                return self._json(200, hub.agenten())
            if url.path == "/api/pos":
                return self._json(200, pos.stand())
            if url.path == "/api/wuensche":
                return self._json(200, wuensche.liste())
            if url.path.startswith("/api/wuensche/") and len(teile) == 1:
                return self._json(200, wuensche.zeigen(teile[0]))
            if url.path == "/api/berichte":
                return self._json(200, berichte.liste())
            if url.path == "/api/berichte/warten":
                if aid == hub.BESITZER:
                    return self._json(400, {"fehler": "Warten ist für Agenten."})
                return self._json(200, berichte.warten(aid, arg("sitzung"), arg("sekunden", "600")))
            if url.path.startswith("/api/berichte/") and len(teile) == 1:
                return self._json(200, berichte.lesen(aid, teile[0]))
            if url.path == "/api/laeufe":
                return self._json(200, laeufe.lage())
            if url.path == "/api/papierkorb":
                return self._json(200, papierkorb.liste())
            if url.path == "/api/notizen":
                return self._json(200, notizen.liste())
            if url.path == "/api/notizen/notiz":
                return self._json(200, notizen.lesen(arg("pfad")))
            if url.path == "/api/notizen/suche":
                return self._json(200, {"treffer": notizen.suche(arg("q"))})
            if url.path == "/api/finanzen" or url.path.startswith("/api/finanzen/"):
                r = finanzen.api_get(url.path.split("/")[3:], q)
                if r is None:
                    return self._json(404, {"fehler": "unbekannt"})
                return self._json(200, r[1]) if r[0] == "json" else self._send(200, r[1], r[2])
        except ValueError as e:
            return self._json(400, {"fehler": str(e)})
        if url.path == "/melder.py":
            try:
                return self._send(200, MELDER.read_bytes(), "text/x-python; charset=utf-8")
            except FileNotFoundError:
                return self._json(404, {"fehler": "melder.py fehlt"})
        if url.path in ("/", "/index.html"):
            try:
                return self._send(200, SEITE.read_bytes(), "text/html; charset=utf-8")
            except FileNotFoundError:
                return self._send(500, "index.html fehlt. Bitte `py zentrale/bauen.py` (Mac/Linux: python3) laufen lassen.".encode(), "text/plain; charset=utf-8")
        self._json(404, {"fehler": "unbekannt"})

    def do_POST(self):
        v = self._vorab()
        if not v:
            return
        url, aid = v
        if not aid:
            return self._json(401, {"fehler": "Schlüssel fehlt oder ist falsch."})
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = -1
        # Finanzen: Kontoauszüge kommen als Datei (base64, bis 10 MB)
        grenze = finanzen.UPLOAD_MAX if url.path == "/api/finanzen/upload" else 4 * 1024 * 1024 if url.path.startswith("/api/finanzen/") \
            else GROSS if url.path.startswith(("/api/berichte", "/api/notizen")) else hub.MAX_BODY
        if n < 0 or n > grenze:
            return self._json(413, {"fehler": "Die Anfrage ist zu groß."})
        teile = url.path.split("/")[3:]
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("JSON-Objekt erwartet")
            r = self._post(aid, url.path, teile, body)
        except PermissionError as e:
            return self._json(403, {"fehler": str(e)})
        except (ValueError, AttributeError, TypeError, KeyError) as e:
            return self._json(400, {"fehler": str(e)})
        if r is None:
            return self._json(404, {"fehler": "unbekannt"})
        self._json(200, r)

    def _post(self, aid, pfad, teile, b):
        if pfad == "/api/geraete/melden":
            return geraete.melden(aid, b)
        if pfad.startswith("/api/geraete/") and len(teile) == 2 and teile[1] == "vergessen":
            if aid != hub.BESITZER:
                raise PermissionError("Ein Gerät vergessen darf nur der Besitzer.")
            return geraete.vergessen(teile[0])
        if pfad.startswith("/api/finanzen/"):
            return finanzen.api_post(aid, teile, b)
        if pfad.startswith("/api/pos/"):
            # /api/pos/projekte[/<id>], /api/pos/aufgaben[/<id>]
            if teile == ["projekte"]:
                return pos.projekt_neu(aid, b)
            if len(teile) == 2 and teile[0] == "projekte":
                return pos.projekt_aendern(aid, unquote(teile[1]), b)   # Namen mit Leerzeichen und Umlauten kommen kodiert an
            if teile == ["aufgaben"]:
                return pos.aufgabe_neu(aid, b)
            if len(teile) == 2 and teile[0] == "aufgaben":
                return pos.aufgabe_aendern(aid, teile[1], b)
        if pfad == "/api/wuensche":
            return wuensche.neu(aid, b)
        if pfad.startswith("/api/wuensche/"):
            if len(teile) == 1:
                return wuensche.aendern(aid, teile[0], b)
            if len(teile) == 2 and teile[1] == "notizen":
                return wuensche.notiz(aid, teile[0], b)
            if len(teile) == 4 and teile[1] == "notizen" and teile[3] == "loeschen":
                return wuensche.notiz_loeschen(aid, teile[0], teile[2])
        if pfad == "/api/berichte":
            return berichte.neu(aid, b)
        if pfad.startswith("/api/berichte/") and len(teile) == 2:
            if teile[1] == "nachricht":
                return berichte.nachricht(aid, teile[0], b)
            if teile[1] == "abgeholt":
                return berichte.abgeholt(aid, teile[0], b.get("nachrichten"))
            if teile[1] == "erledigt":
                return berichte.erledigt(aid, teile[0], b)
            if teile[1] == "gelesen":
                if aid != hub.BESITZER:
                    raise PermissionError("Gelesen setzt nur der Besitzer.")
                return berichte.gelesen(teile[0], b.get("ja", True))
        if pfad == "/api/laeufe":
            if aid == hub.BESITZER:
                raise PermissionError("Läufe melden nur Agenten.")
            return laeufe.melden(aid, b)
        if pfad == "/api/papierkorb/zurueck":
            return papierkorb.zuruecklegen(b)
        if pfad == "/api/papierkorb/loeschen":
            if aid != hub.BESITZER:
                raise PermissionError("Endgültig löschen darf nur der Besitzer. Agenten verschieben nur in den Papierkorb.")
            return papierkorb.loeschen(b)
        if pfad == "/api/notizen/neu":
            return notizen.neu(b.get("ordner"), b.get("titel"), b.get("text"))
        if pfad == "/api/notizen/speichern":
            return notizen.speichern(b.get("pfad"), b.get("text"), b.get("version"))
        if pfad == "/api/notizen/papierkorb":
            return notizen.in_papierkorb(b.get("pfad"), aid)
        return None

    def log_message(self, *args):
        pass


def starten(bind="127.0.0.1", port=8090, lan=False):
    hub.PORT = port
    hub.LAN_OFFEN = lan
    hub.HEIMNETZ = bind not in ("127.0.0.1", "localhost", "::1")
    if hub.HEIMNETZ:   # den eigenen Rechnernamen als Adresse annehmen (http://<name>:8090, http://<name>.local:8090)
        n = socket.gethostname().lower()
        EIGENE_NAMEN.update({n, n.split(".")[0], n.split(".")[0] + ".local"})
    try:
        notizen.grundgeruest()
    except OSError as e:
        print(f"Grundgerüst der Notizen nicht angelegt: {e}", flush=True)
    ThreadingHTTPServer.daemon_threads = True
    # Unter Windows erlaubt SO_REUSEADDR, dass zwei Programme denselben Port belegen. Das wollen wir nicht.
    ThreadingHTTPServer.allow_reuse_address = os.name != "nt"
    srv = ThreadingHTTPServer((bind, port), Handler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
