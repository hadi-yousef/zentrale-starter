"""Zentrale: Geräte im Homelab (Seiten „Geräte“, „Speicher“, „Netzwerk“, „Dienste“).

Auf jedem Gerät (alter Laptop, PC, Server) läuft der Melder (`melder/melder.py`). Er schickt jede Minute den Zustand:
Betriebssystem, Prozessor, Arbeitsspeicher, Laufwerke mit Papierkorb, Akku, Temperatur, Netzwerk, Updates und bei Linux
die Dienste. Jedes Gerät hat einen eigenen Schlüssel „geraet-<name>“ (`start.py geraet-neu <name>`). Dieser Schlüssel
darf nur melden, sonst nichts (das prüft app.py). Der Name des Geräts kommt immer aus dem Schlüssel.

Gespeichert in DATEN/geraete.json: {"geraete": {id: {id, name, art, erstmals, zuletzt, info: {…letzte Meldung…}}}}
Offline gilt ein Gerät nach 3 Minuten ohne Meldung. Warnungen rechnet die Zentrale bei jeder Abfrage neu aus.
"""
import ipaddress
import os
import re
import shutil
import socket
import subprocess
import threading
import time

import hub

DATEI = hub.STATE_DIR / "geraete.json"
PRAEFIX = "geraet-"
OFFLINE_S = 180
MELDER_FASSUNG = 1          # gleich wie FASSUNG in melder/melder.py; ältere Melder bekommen einen Hinweis
ARTEN = ("windows", "mac", "linux")
_lock = threading.Lock()
_d = hub._json_laden(DATEI, {})
_geraete = dict(_d.get("geraete") or {})
_gespeichert = 0.0


def ist_geraet(aid):
    return bool(aid) and aid.startswith(PRAEFIX)


def _sichern(sofort=False):
    """Höchstens alle 5 Minuten auf die Platte (jede Minute kommt von jedem Gerät eine Meldung). Unter _lock aufrufen."""
    global _gespeichert
    if sofort or time.time() - _gespeichert > 300:
        _gespeichert = time.time()
        try:
            hub.json_schreiben(DATEI, {"geraete": _geraete})
        except OSError:
            pass


# ---------- Meldung prüfen: nur bekannte Felder, Zahlen als Zahlen, Texte gekürzt ----------

def _t(v, n=120):
    return re.sub(r"\s+", " ", str(v)).strip()[:n] if v not in (None, "") else ""


def _z(v, lo=None, hi=None):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x:   # NaN
        return None
    if lo is not None and x < lo:
        return None
    if hi is not None and x > hi:
        x = hi
    return round(x, 2)


def _ganz(v, lo=0):
    x = _z(v, lo)
    return int(x) if x is not None else None


def _ja(v):
    return None if v is None else bool(v)


def _liste(v, n):
    return v[:n] if isinstance(v, list) else []


def _laufwerk(x):
    if not isinstance(x, dict):
        return None
    g = _ganz(x.get("gesamt"))
    if not g:
        return None
    f = _ganz(x.get("frei"))
    return {"lw": _t(x.get("lw"), 200), "name": _t(x.get("name"), 80), "gesamt": g, "frei": min(f, g) if f is not None else None,
            "fs": _t(x.get("fs"), 20), "art": _t(x.get("art"), 20) or "intern", "papierkorb": _ganz(x.get("papierkorb"))}


def bereinigen(m):
    """Aus der Meldung nur übernehmen, was die Seiten kennen."""
    if not isinstance(m, dict):
        raise ValueError("Meldung muss ein JSON-Objekt sein.")
    art = _t(m.get("art"), 10).lower()
    a = m.get("akku") if isinstance(m.get("akku"), dict) else None
    ts = m.get("tailscale") if isinstance(m.get("tailscale"), dict) else None
    di = m.get("dienste") if isinstance(m.get("dienste"), dict) else None
    return {
        "melder": _ganz(m.get("melder")) or 0,
        "art": art if art in ARTEN else "",
        "name": _t(m.get("name"), 60),
        "rechnername": _t(m.get("rechnername"), 80),
        "system": _t(m.get("system"), 120),
        "modell": _t(m.get("modell"), 120),
        "cpu_name": _t(m.get("cpu_name"), 120),
        "kerne": _ganz(m.get("kerne")),
        "seit": _ganz(m.get("seit")),
        "cpu": _z(m.get("cpu"), 0, 100),
        "ram_gesamt": _ganz(m.get("ram_gesamt")),
        "ram_belegt": _ganz(m.get("ram_belegt")),
        "temp": _z(m.get("temp"), -40, 150),
        "laufwerke": [l for l in (_laufwerk(x) for x in _liste(m.get("laufwerke"), 30)) if l],
        "akku": None if not a else {"prozent": _z(a.get("prozent"), 0, 100), "netzteil": _ja(a.get("netzteil")), "laedt": _ja(a.get("laedt")),
                                    "zyklen": _ganz(a.get("zyklen")), "zustand": _t(a.get("zustand"), 40), "kapazitaet": _z(a.get("kapazitaet"), 0, 150)},
        "ip": [_t(x, 45) for x in _liste(m.get("ip"), 8) if _t(x, 45)],
        "tailscale": None if not ts else {"an": bool(ts.get("an")), "ip": _t(ts.get("ip"), 45), "name": _t(ts.get("name"), 80)},
        "updates": _ganz(m.get("updates")),
        "neustart": _ja(m.get("neustart")),
        "dienste": None if not di else {"laufend": _ganz(di.get("laufend")), "fehler": [_t(x, 80) for x in _liste(di.get("fehler"), 40) if _t(x, 80)]},
        "docker": [{"name": _t(c.get("name"), 80), "bild": _t(c.get("bild"), 120), "zustand": _t(c.get("zustand"), 80), "laeuft": bool(c.get("laeuft"))}
                   for c in _liste(m.get("docker"), 60) if isinstance(c, dict) and _t(c.get("name"))],
    }


def melden(aid, m):
    """Ein Gerät meldet seinen Zustand. Der Besitzer darf zum Testen für ein Gerät melden („id“ im Inhalt)."""
    if ist_geraet(aid):
        gid = aid[len(PRAEFIX):]
    elif aid == hub.BESITZER:
        gid = _t((m or {}).get("id"), 40)
        if not hub.gueltige_id(gid):
            raise ValueError("Für eine Meldung des Besitzers bitte „id“ angeben (Buchstaben, Ziffern, - und _).")
    else:
        raise PermissionError("Melden dürfen nur Geräte (Schlüssel geraet-…).")
    info = bereinigen(m)
    jetzt = int(time.time())
    with _lock:
        g = _geraete.get(gid) or {"id": gid, "erstmals": jetzt}
        neu = "zuletzt" not in g
        g.update(name=info["name"] or g.get("name") or gid, art=info["art"] or g.get("art", ""), zuletzt=jetzt, info=info)
        _geraete[gid] = g
        _sichern(sofort=neu)
    return {"ok": True, "id": gid, "melder_aktuell": MELDER_FASSUNG}


def vergessen(gid):
    """Ein Gerät aus der Liste nehmen (z. B. verkauft). Sein Schlüssel gilt weiter, bis `start.py agent-weg geraet-…`."""
    with _lock:
        if gid not in _geraete:
            raise ValueError("Dieses Gerät gibt es nicht.")
        del _geraete[gid]
        _sichern(sofort=True)
    return {"ok": True}


# ---------- Warnungen (wie „Zu tun“ im Vorbild) ----------

def _gr(b):
    for e in ("B", "KB", "MB", "GB", "TB"):
        if b < 1000 or e == "TB":
            return (f"{b:.0f} {e}" if e in ("B", "KB") or b >= 100 else f"{b:.1f} {e}").replace(".", ",")
        b /= 1000


def _warnungen(g, jetzt):
    W, i, gid, name = [], g.get("info") or {}, g["id"], g.get("name") or g["id"]
    weg = jetzt - (g.get("zuletzt") or 0)

    def w(stufe, art, titel, text):
        W.append({"id": f"{gid}|{art}", "geraet": gid, "stufe": stufe, "titel": titel, "text": text})
    if weg > 86400:
        w("warn", "offline", f"{name} ist offline", f"seit {int(weg // 86400)} {'Tag' if weg < 172800 else 'Tagen'} keine Meldung")
        return W   # alte Werte nicht mehr bewerten
    for l in i.get("laufwerke") or []:
        if l.get("art") == "netz" or not l.get("gesamt") or l.get("frei") is None:
            continue
        p = 100 * (l["gesamt"] - l["frei"]) / l["gesamt"]
        if p >= 90:
            w("bad" if p >= 95 else "warn", "platte-" + l["lw"], f"{name}: {l['lw']} fast voll",
              f"{p:.0f} % belegt, nur noch {_gr(l['frei'])} frei" + (f", davon {_gr(l['papierkorb'])} im Papierkorb" if l.get("papierkorb") else ""))
    a = i.get("akku") or {}
    if a.get("prozent") is not None and a["prozent"] < 20 and not a.get("netzteil"):
        w("warn", "akku", f"{name}: Akku fast leer", f"{a['prozent']:.0f} %, nicht am Netzteil")
    if a.get("kapazitaet") is not None and a["kapazitaet"] < 70 or re.search(r"service|replace|poor|ersetzen|schlecht", a.get("zustand") or "", re.I):
        w("info", "akkuzustand", f"{name}: Akku verschlissen", ", ".join(x for x in (
            f"noch {a['kapazitaet']:.0f} % der ursprünglichen Kapazität" if a.get("kapazitaet") is not None else "",
            f"{a['zyklen']} Ladezyklen" if a.get("zyklen") else "", a.get("zustand") or "") if x))
    for d in ((i.get("dienste") or {}).get("fehler") or [])[:5]:
        w("bad", "dienst-" + d, f"Dienst ausgefallen: {d}", f"auf {name}")
    for c in i.get("docker") or []:
        if not c["laeuft"] and re.search(r"exited \((?!0\))|restarting|dead", c["zustand"], re.I):
            w("warn", "docker-" + c["name"], f"Container gestoppt: {c['name']}", f"auf {name}, {c['zustand']}")
    if i.get("temp") is not None and i["temp"] >= 85:
        w("warn", "temp", f"{name} ist heiß", f"{i['temp']:.0f} °C")
    if i.get("neustart"):
        w("info", "neustart", f"{name} braucht einen Neustart", "nach Updates")
    if i.get("updates"):
        w("info", "updates", f"{name}: {i['updates']} Updates warten", "einspielen, wenn es passt")
    if (i.get("melder") or 0) < MELDER_FASSUNG:
        w("info", "melder", f"{name}: alter Melder", "melder.py auf diesem Gerät erneuern")
    return W


def _eigene_ip(ziel):
    """Welche eigene Adresse nimmt der Rechner für dieses Ziel? Schickt nichts, wählt nur die Netzwerkkarte."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((ziel, 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return ""


_ts = {"zeit": 0, "ip": ""}


def tailscale_ip():
    """Eigene Tailscale-Adresse oder "" (fragt `tailscale ip -4`, wie der Melder; höchstens einmal in der Minute)."""
    if time.time() - _ts["zeit"] < 60:
        return _ts["ip"]
    prog = shutil.which("tailscale")
    for p in (r"C:\Program Files\Tailscale\tailscale.exe", "/Applications/Tailscale.app/Contents/MacOS/Tailscale"):
        if not prog and os.path.exists(p):
            prog = p
    ip = ""
    if prog:
        try:
            r = subprocess.run([prog, "ip", "-4"], capture_output=True, text=True, timeout=5,
                               creationflags=0x08000000 if os.name == "nt" else 0)   # CREATE_NO_WINDOW: kein Konsolenfenster
            ip = (r.stdout.split() or [""])[0] if r.returncode == 0 else ""
            ip = ip if ipaddress.ip_address(ip) in ipaddress.ip_network("100.64.0.0/10") else ""
        except (OSError, ValueError, subprocess.SubprocessError):
            ip = ""
    _ts.update(zeit=time.time(), ip=ip)
    return ip


def adressen():
    """Wie andere Geräte die Zentrale erreichen: die Tailscale-Adresse, mit --lan-unverschluesselt auch die im Heimnetz.
    ZENTRALE_ADRESSEN (mit Komma) ersetzt sie, z. B. „http://heimserver:8090“ für einen Tailscale-Namen (MagicDNS)."""
    if os.environ.get("ZENTRALE_ADRESSEN"):
        return [a.strip() for a in os.environ["ZENTRALE_ADRESSEN"].split(",") if a.strip()]
    A = [tailscale_ip()]
    if hub.LAN_OFFEN:
        A.append(_eigene_ip("10.255.255.255"))
    return [f"http://{a}:{hub.PORT}" for a in A if a and not a.startswith("127.")]


def abgewiesen():
    """Adressen aus dem Heimnetz, die in der letzten Stunde abgewiesen wurden (z. B. ein Melder mit der alten Adresse)."""
    grenze = int(time.time()) - 3600
    return sorted(ip for ip, t in list(hub.ABGEWIESEN.items()) if t >= grenze)


def liste():
    jetzt = int(time.time())
    with _lock:
        G = [dict(g) for g in _geraete.values()]
    rang = {"bad": 0, "warn": 1, "info": 2}
    W = []
    for g in G:
        g["online"] = jetzt - (g.get("zuletzt") or 0) <= OFFLINE_S
        g["warnungen"] = sorted(_warnungen(g, jetzt), key=lambda w: rang[w["stufe"]])
        W += g["warnungen"]
    G.sort(key=lambda g: (not g["online"], (g.get("info") or {}).get("art") != "linux", (g.get("name") or "").lower()))
    W.sort(key=lambda w: rang[w["stufe"]])
    return {"geraete": G, "warnungen": W, "jetzt": jetzt, "offline_s": OFFLINE_S, "melder_aktuell": MELDER_FASSUNG,
            "zentrale": {"heimnetz": bool(hub.HEIMNETZ), "lan_offen": bool(hub.LAN_OFFEN), "abgewiesen": abgewiesen(),
                         "adressen": adressen() if hub.HEIMNETZ else [], "port": hub.PORT}}
