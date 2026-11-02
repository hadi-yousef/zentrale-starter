#!/usr/bin/env python3
r"""Neue Zentrale einrichten, ohne dass sie sich mit einer alten vermischt, und Updates einspielen.
suchen, alt-zeigen und pruefen ändern nichts, sie lesen und zeigen nur.

  py einrichten.py suchen          alte Zentralen finden: laufende Programme, Ports, Autostart, Ordner, Schlüssel,
                                   Umgebungsvariablen, Hinweise in den Anleitungen der Agenten
  py einrichten.py alt-zeigen <ordner>
                                   was in einer alten Zentrale steht (offene Wünsche, Projekte, Notizen), zum Durchgehen
                                   mit dem Besitzer. Nur lesen.
  py einrichten.py pruefen         nach dem Einrichten: läuft genau diese Zentrale, mit eigenen Daten und Schlüsseln?
                                   Ende mit Code 0 = alles getrennt, 1 = etwas ist noch vermischt.
  py einrichten.py update          neue Fassung holen, ohne dass etwas verloren geht: Daten zählen, eigene Änderungen in
                                   einen Sicherungszweig, holen (auch nach neu geschriebener Geschichte), Regeln verteilen,
                                   Zentrale neu starten, Fassung und Daten prüfen. --ordner <Zentrale>, wenn von woanders gestartet
  (Mac und Linux: python3 statt py)

Ablauf und was der Agent dabei tut: docs/EINRICHTEN.md.
"""
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

HIER = Path(__file__).resolve().parent
WIN = os.name == "nt"
PY = "py" if WIN else "python3"
ID = hashlib.sha256(str(HIER).lower().encode("utf-8")).hexdigest()[:12]   # gleich wie hub.ORDNER_ID
SCHLUESSEL = Path(os.environ.get("ZENTRALE_SCHLUESSEL_ORDNER") or Path.home() / ".config" / "zentrale-starter")
PORTS = sorted(set(range(8000, 8101)) | {3000, 5000, 5173, 8443, 8888, 9000})
OHNE = {"appdata", "node_modules", ".git", "library", "venv", ".venv", "__pycache__", "onedrive", "$recycle.bin",
        "papierkorb", "windows", "program files", "program files (x86)", ".cache", ".npm", ".cargo", ".rustup"}
try:
    sys.stdout.reconfigure(errors="replace")
except (AttributeError, ValueError):
    pass


def fassung():
    m = re.search(r'FASSUNG = "([^"]+)"', (HIER / "zentrale" / "hub.py").read_text(encoding="utf-8"))
    return m.group(1) if m else "?"


def holen(url, schluessel=None, zeit=1.5):
    r = urllib.request.Request(url, headers={"Authorization": "Bearer " + schluessel} if schluessel else {})
    with urllib.request.urlopen(r, timeout=zeit) as a:
        return a.status, a.read(200_000).decode("utf-8", "replace")


def ports():
    """Was auf diesem Rechner auf einem der üblichen Ports antwortet und wie eine Zentrale aussieht."""
    funde = []
    for p in PORTS:
        try:
            socket.create_connection(("127.0.0.1", p), timeout=0.15).close()
        except OSError:
            continue
        art, info = "", ""
        try:
            _, t = holen(f"http://127.0.0.1:{p}/api/lebt")
            d = json.loads(t)
            if d.get("zentrale") == "starter":
                art = "diese" if d.get("ordner_id") == ID else "andere Starter-Zentrale"
                info = f"Fassung {d.get('fassung')}"
            elif d.get("ok"):
                art, info = "ältere Zentrale", "antwortet auf /api/lebt, ohne Kennung (vor Fassung 2026-11-02 oder eigene)"
        except Exception:
            pass
        if not art:
            try:
                _, t = holen(f"http://127.0.0.1:{p}/")
                titel = (re.search(r"<title>(.*?)</title>", t, re.S | re.I) or [None, ""])[1].strip()
                if re.search(r"zentrale", titel + t[:3000], re.I):
                    art, info = "Zentrale (unbekannt)", f"Titel „{titel}“"
            except Exception:
                pass
        if art:
            funde.append((p, art, info))
    return funde


def ps(befehl):
    try:
        return subprocess.run(["powershell", "-NoProfile", "-Command", befehl], capture_output=True, text=True,
                              timeout=40, encoding="utf-8", errors="replace").stdout
    except Exception:
        return ""


def prozesse():
    """Python-Programme, die nach einer Zentrale aussehen (start.py, app.py, zentrale …)."""
    if WIN:
        t = ps("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'start\\.py|zentrale.*app\\.py' "
               "-and $_.Name -match 'py' } | ForEach-Object { \"$($_.ProcessId)`t$($_.CommandLine)\" }")
    else:
        try:
            t = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True, timeout=10).stdout
        except Exception:
            t = ""
        t = "\n".join("\t".join(z.strip().split(None, 1)) for z in t.splitlines()
                      if re.search(r"python", z, re.I) and re.search(r"start\.py|zentrale.*app\.py", z, re.I))
    aus, fremd_am_port = [], None
    for z in t.splitlines():
        if "\t" not in z or "einrichten.py" in z:
            continue
        pid, cmd = z.split("\t", 1)
        eigen = str(HIER).lower() in cmd.lower()
        if not eigen and re.search(r"(^|\s)\"?start\.py", cmd):
            # „py start.py“ ohne Pfad: welcher Ordner, sieht man nicht. Dann zählt, ob nur diese Zentrale antwortet.
            if fremd_am_port is None:
                fremd_am_port = any(art != "diese" for _, art, _ in ports())
            eigen = None if fremd_am_port else True   # None = unklar
        aus.append((pid.strip(), cmd.strip(), eigen))
    return aus


def autostart():
    if WIN:
        t = ps("Get-ScheduledTask | ForEach-Object { $a = ($_.Actions | ForEach-Object { \"$($_.Execute) $($_.Arguments) "
               "$($_.WorkingDirectory)\" }) -join ' | '; if ($_.TaskName -match 'zentrale' -or $a -match 'zentrale') "
               "{ \"$($_.TaskName)`t$($_.State)`t$a\" } }")
        aus = []
        for z in t.splitlines():
            if z.count("\t") >= 2:
                n, st, a = z.split("\t", 2)
                aus.append((n.strip(), st.strip(), a.strip(), str(HIER).lower() in a.lower()))
        return aus
    d = Path.home() / "Library" / "LaunchAgents"
    aus = []
    for f in (d.glob("*.plist") if d.exists() else []):
        t = f.read_text(errors="replace")
        if re.search(r"start\.py", t) and re.search(r"zentrale", t, re.I):
            aus.append((f.name, "launchd", f.stem, str(HIER) in t))
    return aus


def ordner():
    """Ordner mit einer anderen Zentrale unter dem Benutzerordner (höchstens 4 Ebenen tief)."""
    funde, start = [], Path.home()
    for wurzel, dirs, files in os.walk(start):
        tiefe = len(Path(wurzel).relative_to(start).parts)
        dirs[:] = [d for d in dirs if d.lower() not in OHNE and not d.startswith(".") and tiefe < 4]
        f = set(files)
        p = Path(wurzel)
        if p.resolve() == HIER:
            dirs[:] = []
            continue
        if "zentrale_client.py" in f or ("start.py" in f and (p / "zentrale").is_dir()) or \
           ({"app.py", "index.html"} <= f and "zentrale" in str(p).lower()) or "index.src.html" in f:
            daten = [str(x.relative_to(p)) for x in (p / "daten", p / "zentrale" / "daten", p / "data") if x.exists()]
            funde.append((p, daten))
            dirs[:] = []
    return funde


def anleitungen():
    """Zeilen in den Anleitungen der Agenten, die auf eine andere Zentrale zeigen (anderer Ordner oder Port)."""
    aus = []
    for f in (Path.home() / ".claude" / "CLAUDE.md", Path.home() / ".codex" / "AGENTS.md"):
        if not f.exists():
            continue
        for i, z in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if re.search(r"zentrale", z, re.I) and (re.search(r"127\.0\.0\.1:(?!8090\b)\d+|localhost:(?!8090\b)\d+", z) or
                                                     (re.search(r"[A-Za-z]:\\|/Users/|/home/", z) and str(HIER).lower() not in z.lower()
                                                      and "zentrale-starter" not in z.lower())):
                aus.append((f, i, z.strip()[:160]))
    return aus


def umgebung():
    aus = []
    for k in ("ZENTRALE_DATEN", "ZENTRALE_URL", "ZENTRALE_PORT", "ZENTRALE_NOTIZEN", "ZENTRALE_SCHLUESSEL_ORDNER"):
        v = os.environ.get(k)
        if v:
            # ZENTRALE_URL darf auf einen Server im Homelab zeigen (docs/HOMELAB.md); welche Zentrale dort läuft, prüft `pruefen`
            fremd = k in ("ZENTRALE_DATEN", "ZENTRALE_NOTIZEN") and str(HIER).lower() not in v.lower()
            aus.append((k, v, fremd))
    return aus


def suchen():
    print(f"Diese Zentrale: {HIER}  (Fassung {fassung()}, Daten in {HIER / 'daten'})\n")
    probleme = 0

    print("1. Was auf den Ports antwortet")
    P = ports()
    for p, art, info in P:
        print(f"   127.0.0.1:{p}  {art}  {info}")
        probleme += art != "diese"
    print("   " + ("" if P else "keine Zentrale läuft") + "\n")

    print("2. Laufende Programme")
    R = prozesse()
    for pid, cmd, eigen in R:
        print(f"   PID {pid}  {'diese' if eigen else 'ANDERE' if eigen is False else 'unklar (ohne Pfad gestartet)'}  {cmd[:150]}")
        probleme += eigen is not True
    print("   " + ("" if R else "keine") + "\n")

    print("3. Autostart")
    A = autostart()
    for n, st, a, eigen in A:
        print(f"   „{n}“ ({st})  {'diese' if eigen else 'ANDERE'}  {a[:150]}")
        probleme += not eigen and st.lower() != "disabled"
    print("   " + ("" if A else "keiner") + "\n")

    print("4. Ordner mit einer anderen Zentrale (unter " + str(Path.home()) + ")")
    O = ordner()
    for p, daten in O:
        print(f"   {p}" + (f"  · Daten: {', '.join(daten)}" if daten else ""))
    probleme += len(O)
    print("   " + ("" if O else "keine") + "\n")

    print("5. Schlüssel der Agenten")
    keys = sorted(SCHLUESSEL.glob("*.key")) if SCHLUESSEL.exists() else []
    print(f"   {SCHLUESSEL}: " + (", ".join(k.stem for k in keys) if keys else "noch keine"))
    for x in sorted(Path.home().joinpath(".config").glob("zentrale*")) if Path.home().joinpath(".config").exists() else []:
        if x.resolve() != SCHLUESSEL.resolve():
            print(f"   ANDERER Schlüsselordner: {x}")
            probleme += 1
    print()

    print("6. Umgebungsvariablen")
    U = umgebung()
    for k, v, fremd in U:
        print(f"   {k}={v}" + ("  ← zeigt auf eine andere Zentrale" if fremd else ""))
        probleme += fremd
    print("   " + ("" if U else "keine gesetzt (gut)") + "\n")

    print("7. Anleitungen der Agenten")
    L = anleitungen()
    for f, i, z in L:
        print(f"   {f}:{i}  {z}")
    probleme += len(L)
    print("   " + ("" if L else "nichts, was auf eine andere Zentrale zeigt") + "\n")

    print(f"Ergebnis: {probleme} Stelle(n) gehören zu einer anderen Zentrale." if probleme else
          "Ergebnis: keine andere Zentrale gefunden.")
    if probleme:
        print("Weiter nach docs/EINRICHTEN.md, Schritt 2 (alte anhalten). Nichts löschen, nichts verschieben.")
    return probleme


def alt_zeigen(pfad):
    p = Path(pfad).expanduser().resolve()
    if p == HIER:
        sys.exit("Das ist diese Zentrale, nicht die alte.")
    kand = [x for x in (p / "daten", p / "zentrale" / "daten", p / "data", p) if x.is_dir()]
    if not kand:
        sys.exit(f"Ordner {p} gibt es nicht.")
    d = next((x for x in kand if (x / "wuensche.json").exists() or (x / "pos.json").exists()), kand[0])
    print(f"Alte Zentrale: {p}\nDaten: {d}\n")

    def lade(n):
        try:
            return json.loads((d / n).read_text(encoding="utf-8"))
        except Exception:
            return None

    w = lade("wuensche.json")
    if w and isinstance(w.get("wuensche"), list):
        offen = [x for x in w["wuensche"] if x.get("status", "offen") == "offen"]
        print(f"Offene Wünsche: {len(offen)}")
        for x in offen:
            print(f"   Nr. {x.get('nr', '?')}  [{x.get('prio') or 'ohne'}]  {x.get('titel', '')}")
            if x.get("text"):
                print(f"      {str(x['text'])[:200]}")
        print()
    pos = lade("pos.json")
    if pos and isinstance(pos.get("projekte"), list):
        P = [x for x in pos["projekte"] if x.get("status", "aktiv") != "archiv"]
        print(f"Projekte: {len(P)}")
        for x in P:
            print(f"   {x.get('name', '')}  ({x.get('status', '')})  Als Nächstes: {x.get('naechster_schritt') or '–'}")
        A = [x for x in pos.get("aufgaben", []) if not x.get("erledigt") and not x.get("entfernt")]
        print(f"Offene Aufgaben: {len(A)}")
        for x in A[:50]:
            print(f"   {x.get('titel', '')}  (für {x.get('fuer', '?')})")
        print()
    n = d / "notizen"
    if n.is_dir():
        N = sorted(x for x in n.rglob("*.md") if "papierkorb" not in str(x).lower())
        print(f"Notizen: {len(N)}")
        for x in N:
            print(f"   {x.relative_to(n)}")
        print()
    if not (w or pos or n.is_dir()):
        print("Kein bekanntes Format (keine wuensche.json, pos.json, notizen). Dateien im Ordner:")
        for x in sorted(d.iterdir())[:60]:
            print(f"   {x.name}{'/' if x.is_dir() else ''}")
    print("\nNichts davon wird von selbst übernommen. Mit dem Besitzer einzeln durchgehen (docs/EINRICHTEN.md, Schritt 5).")


def pruefen():
    fehler = []
    url = (os.environ.get("ZENTRALE_URL") or "http://127.0.0.1:8090").rstrip("/")
    try:
        _, t = holen(url + "/api/lebt", zeit=3)
        d = json.loads(t)
        # Läuft die Zentrale auf einem anderen Gerät (Homelab-Server), lässt sich der Ordner nicht vergleichen, nur die Fassung
        lokal = urllib.parse.urlsplit(url).hostname in ("127.0.0.1", "localhost", "::1")
        if d.get("zentrale") != "starter":
            fehler.append(f"Auf {url} läuft keine Zentrale aus diesem Repo (oder eine sehr alte).")
        elif lokal and d.get("ordner_id") != ID:
            fehler.append(f"Auf {url} läuft eine andere Zentrale (nicht aus {HIER}).")
        elif d.get("fassung") != fassung():
            fehler.append(f"Auf {url} läuft Fassung {d.get('fassung')}, dieser Ordner hat {fassung()}: neu starten.")
    except Exception as e:
        fehler.append(f"Auf {url} antwortet keine Zentrale ({e}). `{PY} start.py` starten.")
    for a in ("claude", "codex"):
        k = SCHLUESSEL / f"{a}.key"
        if not k.exists():
            fehler.append(f"Schlüssel für {a} fehlt: `{PY} start.py agent-neu {a}`.")
            continue
        try:
            _, t = holen(url + "/api/ich", k.read_text(encoding="utf-8").strip(), 3)
            if json.loads(t).get("id") != a:
                fehler.append(f"Schlüssel von {a} gehört zu einem anderen Agenten.")
        except Exception:
            fehler.append(f"Schlüssel von {a} passt nicht zu dieser Zentrale (alter Schlüssel?): `{PY} start.py agent-neu {a}`.")
    for pid, cmd, eigen in prozesse():
        if eigen is False:
            fehler.append(f"Eine andere Zentrale läuft noch: PID {pid} ({cmd[:100]}).")
        elif eigen is None:
            fehler.append(f"PID {pid} wurde ohne Pfad gestartet ({cmd[-60:]}), und es antwortet noch eine andere Zentrale. "
                          "Welche es ist: Task-Manager, Spalte Befehlszeile, oder `suchen`.")
    for n, st, a, eigen in autostart():
        if not eigen and st.lower() != "disabled":
            fehler.append(f"Autostart „{n}“ startet eine andere Zentrale ({a[:100]}). Deaktivieren (nicht löschen).")
    for k, v, fremd in umgebung():
        if fremd:
            fehler.append(f"Umgebungsvariable {k}={v} zeigt auf eine andere Zentrale.")
    for f, i, z in anleitungen():
        fehler.append(f"{f}, Zeile {i} zeigt auf eine andere Zentrale: {z[:100]}")
    if fehler:
        print("Noch vermischt:")
        for x in fehler:
            print("   • " + x)
        return 1
    if urllib.parse.urlsplit(url).hostname in ("127.0.0.1", "localhost", "::1"):
        print(f"Alles getrennt: Es läuft nur die Zentrale aus {HIER} (Fassung {fassung()}), mit eigenen Daten und Schlüsseln.")
    else:
        print(f"Alles getrennt: Die Zentrale auf {url} (Fassung {fassung()}) nimmt die Schlüssel dieses Geräts, hier läuft keine andere.")
    return 0


def daten_zaehlen():
    """Wie viele Einträge die Zentrale hat (aus den Dateien in daten\\), zum Vergleich vor und nach dem Update."""
    d = Path(os.environ.get("ZENTRALE_DATEN") or HIER / "daten")
    def lade(n):
        try:
            return json.loads((d / n).read_text(encoding="utf-8"))
        except Exception:
            return {}
    pos = lade("pos.json")
    z = {"Wünsche": len(lade("wuensche.json").get("wuensche", [])), "Berichte": len(lade("berichte.json").get("berichte", [])),
         "Projekte": len(pos.get("projekte", [])), "Aufgaben": len(pos.get("aufgaben", [])),
         "Notizen": sum(1 for x in (d / "notizen").rglob("*.md")) if (d / "notizen").is_dir() else 0}
    return d, z


def quelle_finden(git):
    """Name der Git-Quelle für Updates: die offizielle Adresse, sonst origin, sonst die einzige. Sonst leer."""
    namen = git("remote").stdout.split()
    for n in namen:
        if re.search(r"github\.com[/:]hadi-yousef/zentrale-starter(\.git)?/?$", git("remote", "get-url", n).stdout.strip(), re.I):
            return n
    if "origin" in namen:
        return "origin"
    return namen[0] if len(namen) == 1 else ""


def update():
    """Neue Fassung holen, ohne dass etwas verloren geht:
    1. Daten zählen, eigene Änderungen (nicht hochgeladen, auch committete) in einen Sicherungszweig legen
    2. neue Fassung holen: vorspulen, oder, wenn die Geschichte neu geschrieben wurde, auf den neuen Stand setzen
    3. Regeln verteilen, Zentrale neu starten, Fassung und Daten prüfen."""
    import time
    def git(*a):
        return subprocess.run(["git", "-C", str(HIER), *a], capture_output=True, text=True, encoding="utf-8", errors="replace")

    def zweig_anlegen(commit):
        """Sicherungszweig mit neuem Namen auf genau diesen Commit. Klappt das nicht nachweislich, bricht das Update ab."""
        soll = git("rev-parse", "--verify", "-q", commit + "^{commit}").stdout.strip()
        basis = "sicherung-vor-update-" + time.strftime("%Y%m%d-%H%M%S")
        name, n = basis, 2
        while git("rev-parse", "--verify", "-q", "refs/heads/" + name).returncode == 0:   # gibt es schon: nie wiederverwenden
            name, n = f"{basis}-{n}", n + 1
        r = git("branch", name, soll or commit)
        ist = git("rev-parse", "--verify", "-q", "refs/heads/" + name).stdout.strip()
        if r.returncode or not soll or ist != soll:
            print((r.stdout + r.stderr).strip())
            sys.exit("Der Sicherungszweig ließ sich nicht sicher anlegen. Nichts geändert.")
        return name

    if not (HIER / ".git").exists():
        sys.exit("Dieser Ordner ist kein Git-Klon. Update: neu klonen (README.md), dann nach docs/EINRICHTEN.md einrichten.")
    quelle = quelle_finden(git)
    if not quelle:
        namen = ", ".join(git("remote").stdout.split()) or "keine"
        sys.exit(f"Ich finde die Quelle für Updates nicht (eingetragen: {namen}). Nichts geändert. "
                 "Trag sie ein: git remote add origin <Adresse des Starter-Repos>")
    ordner_daten, vorher = daten_zaehlen()
    alt = fassung()
    print(f"Zentrale in {HIER}, Fassung {alt}, Daten in {ordner_daten}")
    print("Einträge vorher: " + ", ".join(f"{k} {v}" for k, v in vorher.items()))

    # 1. Eigenes sichern (daten\\ ist nicht in Git und bleibt sowieso unberührt)
    offen = [z for z in git("status", "--porcelain").stdout.splitlines() if z.strip()]
    # Eigene Commits: nicht auf GitHub. Commits, die es dort mit gleichem Text gibt, sind alte Fassungen vor einem Umschreiben.
    git("fetch", "-q", quelle)
    oben = set(git("log", "--format=%s", "--remotes").stdout.splitlines())
    eigene = [z for z in git("log", "--format=%h %s", "HEAD", "--not", "--remotes").stdout.splitlines()
              if z.strip() and z.split(" ", 1)[-1] not in oben]
    sicherung = ""
    if offen or eigene:
        print(f"Eigene Änderungen gefunden ({len(offen)} Dateien geändert, {len(eigene)} eigene Commits). Sichere sie in einem Zweig:")
        for z in (offen + eigene)[:20]:
            print("   " + z)
        if offen:
            # Schnappschuss aller Dateien (ohne daten\\ und anderes aus .gitignore) als Commit, ohne den Ordner anzufassen
            import tempfile
            with tempfile.TemporaryDirectory() as tmp:
                env = dict(os.environ, GIT_INDEX_FILE=str(Path(tmp) / "index"), GIT_AUTHOR_NAME="Zentrale",
                           GIT_AUTHOR_EMAIL="zentrale@localhost", GIT_COMMITTER_NAME="Zentrale", GIT_COMMITTER_EMAIL="zentrale@localhost")
                g = lambda *a: subprocess.run(["git", "-C", str(HIER), *a], capture_output=True, text=True, env=env)
                stand = ""
                # jeder Schritt muss klappen, sonst wird nichts zurückgesetzt
                if g("read-tree", "HEAD").returncode == 0 and g("add", "-A").returncode == 0:
                    w = g("write-tree")
                    baum = w.stdout.strip() if w.returncode == 0 else ""
                    if baum:
                        c = g("commit-tree", baum, "-p", "HEAD", "-m", f"Sicherung vor Update ({len(offen)} geänderte Dateien)")
                        stand = c.stdout.strip() if c.returncode == 0 else ""
                # Gegenprobe: enthält der Schnappschuss den Ordner so, wie er jetzt ist?
                if stand and g("diff", "--quiet", stand).returncode != 0:
                    stand = ""
            if not stand:
                sys.exit("Sichern hat nicht geklappt. Nichts geändert.")
            sicherung = zweig_anlegen(stand)
        else:
            sicherung = zweig_anlegen("HEAD")
        print(f"Gesichert in Zweig {sicherung}.")

    # 2. Neue Fassung holen
    r = git("fetch", quelle)
    if r.returncode:
        print((r.stdout + r.stderr).strip())
        sys.exit("Holen hat nicht geklappt (Netz?). Nichts geändert" + (f"; deine Änderungen liegen in {sicherung}." if sicherung else "."))
    zweig = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip() or "main"
    ziel = f"{quelle}/{zweig if zweig != 'HEAD' else 'main'}"
    if git("merge-base", "--is-ancestor", "HEAD", ziel).returncode == 0 and not offen:
        r = git("merge", "--ff-only", ziel)
        wie = "vorgespult"
    else:
        if not sicherung:   # Geschichte neu geschrieben: der alte Stand bekommt trotzdem einen Zweig
            sicherung = zweig_anlegen("HEAD")
        r = git("reset", "--hard", ziel)
        wie = "auf den neuen Stand gesetzt (" + ("eigene Änderungen liegen in der Sicherung" if offen else "die Geschichte wurde neu geschrieben") + ")"
    if r.returncode:
        print((r.stdout + r.stderr).strip())
        sys.exit("Update hat nicht geklappt. Dein Stand ist unverändert" + (f", Sicherung in {sicherung}." if sicherung else "."))
    neu = fassung()
    print(f"Fassung {alt} → {neu}: {wie}.")

    # 3. Regeln, Neustart, Prüfung
    subprocess.run([sys.executable, str(HIER / "regeln_verteilen.py")])
    aufgabe = [x for x in autostart() if x[3] and x[1].lower() != "disabled"]
    lief = False
    if WIN and aufgabe:
        for n, *_ in aufgabe:
            ps(f"Stop-ScheduledTask -TaskName '{n}'; Start-Sleep 2; Start-ScheduledTask -TaskName '{n}'")
            print(f"Zentrale über die Aufgabenplanung „{n}“ neu gestartet.")
        url = (os.environ.get("ZENTRALE_URL") or "http://127.0.0.1:8090").rstrip("/")
        for _ in range(15):
            time.sleep(1)
            try:
                if json.loads(holen(url + "/api/lebt")[1]).get("fassung") == neu:
                    lief = True
                    break
            except Exception:
                pass
        print(f"Die Zentrale läuft mit Fassung {neu}." if lief else "Die neue Fassung antwortet noch nicht: `py einrichten.py pruefen`.")
    else:
        print(f"Jetzt die Zentrale neu starten: `{PY} start.py` beenden und wieder starten (mit denselben Schaltern, z. B. --heimnetz).")
    _, nachher = daten_zaehlen()
    print("Einträge nachher: " + ", ".join(f"{k} {v}" for k, v in nachher.items()))
    weniger = [k for k in vorher if nachher.get(k, 0) < vorher[k]]
    if weniger:
        print("ACHTUNG: weniger Einträge als vorher bei " + ", ".join(weniger) + ". Nichts weiter tun, dem Besitzer zeigen.")
    if sicherung:
        print(f"\nDein alter Stand mit allen eigenen Änderungen liegt im Zweig {sicherung}. Was davon die neue Fassung noch nicht kann:")
        print(f"   git diff --stat {ziel} {sicherung}")
        print("Dem Besitzer als Tabelle zeigen. Was er behalten will: als Wunsch eintragen und nach seinem Ja neu einbauen. Den Zweig nicht löschen.")
    print("Neu in dieser Fassung: `git log --oneline -15` und docs/STOLPERSTEINE.md.")
    return 1 if weniger else 0


if __name__ == "__main__":
    a = sys.argv[1:]
    if "--ordner" in a:   # z. B. aus einem Nebenordner gestartet: py <neu>\\einrichten.py update --ordner <Zentrale>
        k = a.index("--ordner")
        HIER = Path(a[k + 1]).expanduser().resolve()
        ID = hashlib.sha256(str(HIER).lower().encode("utf-8")).hexdigest()[:12]
        del a[k:k + 2]
    if not a or a[0] in ("-h", "--help", "hilfe"):
        print(__doc__)
    elif a[0] == "suchen":
        suchen()
    elif a[0] == "alt-zeigen" and len(a) == 2:
        alt_zeigen(a[1])
    elif a[0] == "pruefen":
        sys.exit(pruefen())
    elif a[0] == "update":
        sys.exit(update())
    else:
        sys.exit(__doc__)
