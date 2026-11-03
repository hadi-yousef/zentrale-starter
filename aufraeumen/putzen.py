#!/usr/bin/env python3
r"""Putzrunde: entfernt nur, was sich von selbst neu erzeugt, damit die Platte nicht vollläuft.

  py aufraeumen\putzen.py                 zeigt nur, was weg käme (Probe, ändert nichts)
  py aufraeumen\putzen.py --bericht       Probe, dazu ein Bericht in der Zentrale mit der Frage „Soll ich das entfernen?“
  py aufraeumen\putzen.py --los           entfernt es wirklich (erst nach dem Ja des Besitzers, danach täglich)
  Weitere Schalter: --tage 7 (so lange unberührt), --agent claude, --grenze-gb 30
  Zum Testen: --wurzel <ordner> nimmt diesen Ordner als Benutzerordner (dann auch AppData und Temp darunter).
  (Mac und Linux: python3 statt py, / statt \)

Was weg darf (Regel „Sichern und Aufräumen“ in REGELN.md): nur Neu-Erzeugbares, und nur, wenn es seit --tage Tagen
unberührt ist:
  - .venv / venv neben pyproject.toml, uv.lock oder requirements*.txt (neu mit `uv sync` oder `pip install -r …`)
  - node_modules neben package.json mit Lockfile (neu mit `npm ci` usw.)
  - __pycache__, .pytest_cache, .mypy_cache, .ruff_cache
  - build\ und dist\ neben pyproject.toml oder setup.py, nur wenn eindeutig vom Bauen (siehe bau_rest), *.egg-info
  - Zwischenspeicher von uv, pip und npm, wenn sie größer als 2 GB sind
  - Einträge in %TEMP%, die älter als --tage Tage sind (gesperrte Dateien bleiben einfach)
Nur gemeldet, nie entfernt: mehrere uv-Programme, von uv installierte Python-Versionen.
Nie: Downloads, Dokumente, Bilder, Repos (.git), Daten der Zentrale, OneDrive, alles außerhalb des Benutzerordners
außer %TEMP%. Braucht keine Administratorrechte.

Jede Entfernung steht im Aufräum-Protokoll (aufraeumen\protokoll.jsonl, art „geputzt“). Zurückholen geht nicht und ist
nicht nötig: Es erzeugt sich beim nächsten `uv sync`, `npm ci` oder Start von selbst neu.
Ohne Konsolenfenster (pyw, Aufgabenplanung) schreibt es nach aufraeumen\putzen.log.
"""
import argparse
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER))
import protokoll as P  # noqa: E402

WIN = os.name == "nt"
MAC = sys.platform == "darwin"
CACHE_GRENZE = 2e9
VENV_NAMEN = {".venv", "venv"}
CACHE_NAMEN = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
LOCKS = ("package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb", "bun.lock", "npm-shrinkwrap.json")
WURZEL_NAMEN = ["Projekte", "Projects", "Desktop", "Documents", "Dokumente", "source", "repos", "dev", "code",
                "git", "workspace", "src"]
NICHT_REIN = {".git", "appdata", "library", "papierkorb", "$recycle.bin", ".trash", "node_modules", "downloads"}
TIEFE = 7
OHNE_FENSTER = {"creationflags": 0x08000000} if os.name == "nt" else {}   # CREATE_NO_WINDOW: unter pyw kein Aufblitzen

if sys.stdout is None:   # pyw / Aufgabenplanung: ohne Konsole ins Log
    sys.stdout = sys.stderr = open(HIER / "putzen.log", "a", encoding="utf-8", buffering=1)
try:
    sys.stdout.reconfigure(errors="replace")
except (AttributeError, ValueError):
    pass


# ---------- Hilfen ----------

def da(p):
    """exists() ohne Abbruch: Windows wirft bei manchen Verknüpfungen (Junctions) einen Fehler statt False."""
    try:
        return p.exists()
    except OSError:
        return False


def ist_link(p):
    """Symbolischer Link oder Windows-Junction: nie hinein, nie entfernen."""
    try:
        return p.is_symlink() or bool(getattr(os.path, "isjunction", lambda x: False)(p)) or \
            bool(getattr(p.lstat(), "st_file_attributes", 0) & 0x400)   # FILE_ATTRIBUTE_REPARSE_POINT
    except OSError:
        return True


def messen(p):
    """Größe in Byte, ohne Links zu folgen."""
    p = Path(p)
    try:
        if p.is_symlink() or p.is_file():
            return p.lstat().st_size
    except OSError:
        return 0
    b = 0
    for d, dirs, files in os.walk(p, onerror=lambda e: None):
        dirs[:] = [x for x in dirs if not ist_link(Path(d) / x)]
        for f in files:
            try:
                b += os.lstat(os.path.join(d, f)).st_size
            except OSError:
                pass
    return b


def zuletzt(p, tiefe=2, ohne=()):
    """Jüngste Änderung im Ordner und in den ersten Ebenen darunter (ohne die Ordner in „ohne“)."""
    try:
        neu = p.lstat().st_mtime
    except OSError:
        return 0
    if tiefe and not ist_link(p) and stat.S_ISDIR(p.lstat().st_mode):
        try:
            for k in p.iterdir():
                if k.name not in ohne:
                    neu = max(neu, zuletzt(k, tiefe - 1, ohne))
        except OSError:
            pass
    return neu


def zuletzt_baum(p):
    """Jüngste Änderung im ganzen Baum (jede Datei und jeder Ordner). Lässt sich etwas nicht lesen, gilt der Baum als
    frisch: lieber stehen lassen als etwas Neues entfernen."""
    try:
        neu = p.lstat().st_mtime
    except OSError:
        return time.time()
    if ist_link(p) or not stat.S_ISDIR(p.lstat().st_mode):
        return neu
    kaputt = []
    for d, dirs, files in os.walk(p, onerror=kaputt.append):
        dirs[:] = [x for x in dirs if not ist_link(Path(d) / x)]
        for x in dirs + files:
            try:
                neu = max(neu, os.lstat(os.path.join(d, x)).st_mtime)
            except OSError:
                return time.time()
    return time.time() if kaputt else neu


def in_grenze(p, basis):
    """Liegt p wirklich unter basis, ohne Verknüpfung auf dem Weg dorthin (auch basis selbst darf keine sein)?
    Gilt für die Auswahl und noch einmal direkt vor dem Entfernen."""
    try:
        p, basis = Path(p).absolute(), Path(basis).absolute()
        rel = p.relative_to(basis)
    except ValueError:
        return False
    if not rel.parts:
        return False
    x = basis
    for teil in rel.parts:
        x = x / teil
        if ist_link(x):
            return False
    try:
        return p.resolve() == basis.resolve() / rel
    except OSError:
        return False


def projekt_zuletzt(p):
    """Wann im Projekt zuletzt etwas geändert wurde, ohne die neu erzeugbaren Ordner."""
    return zuletzt(p, 3, ohne=VENV_NAMEN | CACHE_NAMEN | {"node_modules", ".git", "build", "dist"})


def gb(b):
    return P.groesse(b)


def befehl(*args, zeit=60):
    try:
        r = subprocess.run(list(args), capture_output=True, text=True, timeout=zeit, encoding="utf-8", errors="replace", **OHNE_FENSTER)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def laufende():
    """Befehlszeilen und Programmpfade aller laufenden Prozesse (klein geschrieben), um Benutztes zu überspringen."""
    if WIN:
        t = befehl("powershell", "-NoProfile", "-Command",
                   "Get-CimInstance Win32_Process | ForEach-Object { \"$($_.Name)`t$($_.ExecutablePath)`t$($_.CommandLine)\" }")
    else:
        t = befehl("ps", "-axo", "command=")
    return [z.lower() for z in t.splitlines() if z.strip()]


def benutzt(pfad, prozesse):
    s = str(pfad).lower()
    return any(s in z for z in prozesse)


def werkzeug_laeuft(prozesse, namen):
    muster = re.compile(r"(^|[\\/\t ])(" + "|".join(namen) + r")(\.exe|\.cmd)?([\t ]|$)")
    return any(muster.search(z) for z in prozesse)


def entfernen(p):
    """Ordner oder Datei entfernen; schreibgeschützte Dateien (Windows) vorher freigeben. Gibt Fehlertext oder "" zurück."""
    fehler = []

    def nochmal(fn, pfad, info):
        try:
            os.chmod(pfad, stat.S_IWRITE)
            fn(pfad)
        except OSError as e:
            fehler.append(str(e))

    if ist_link(p):
        return "Verknüpfung, bleibt"
    try:
        if p.is_dir():
            shutil.rmtree(p, onerror=nochmal)
        else:
            p.unlink()
    except OSError as e:
        fehler.append(str(e))
    return fehler[0] if fehler else ""


# ---------- Orte ----------

class Orte:
    def __init__(self, wurzel=None):
        self.test = wurzel is not None
        self.heim = Path(wurzel).resolve() if wurzel else Path.home()
        if self.test:
            self.lokal = self.heim / "AppData" / "Local"
            self.temp = self.heim / "AppData" / "Local" / "Temp"
        elif WIN:
            self.lokal = Path(os.environ.get("LOCALAPPDATA") or self.heim / "AppData" / "Local")
            self.temp = Path(tempfile.gettempdir())
        else:
            self.lokal = self.heim / ".cache"
            self.temp = Path(tempfile.gettempdir())

    def wurzeln(self):
        # eine Verknüpfung als Wurzel (z. B. ~/Projects → externe Platte) würde den Bereich erweitern: auslassen
        W = [self.heim / n for n in WURZEL_NAMEN if not ist_link(self.heim / n) and (self.heim / n).is_dir()]
        if WIN or self.test:   # unter Windows liegen Projekte oft direkt im Benutzerordner
            try:
                W += [k for k in self.heim.iterdir() if not ist_link(k) and k.is_dir() and not k.name.startswith(".") and
                      k.name.lower() not in NICHT_REIN and not k.name.lower().startswith("onedrive") and k not in W and
                      (da(k / "pyproject.toml") or da(k / "package.json") or da(k / ".git"))]
            except OSError:
                pass
        return W

    def caches(self):
        """(Name, Ordner, Befehl zum Leeren oder None)."""
        uv = None if self.test else (befehl("uv", "cache", "dir", zeit=20) or None)
        if WIN or self.test:
            C = [("uv", Path(uv) if uv else self.lokal / "uv" / "cache"),
                 ("pip", self.lokal / "pip" / "Cache" if (self.lokal / "pip" / "Cache").exists() else self.lokal / "pip" / "cache"),
                 ("npm", self.lokal / "npm-cache" / "_cacache")]
        elif MAC:
            C = [("uv", Path(uv) if uv else self.heim / ".cache" / "uv"), ("pip", self.heim / "Library" / "Caches" / "pip"),
                 ("npm", self.heim / ".npm" / "_cacache")]
        else:
            C = [("uv", Path(uv) if uv else self.heim / ".cache" / "uv"), ("pip", self.heim / ".cache" / "pip"),
                 ("npm", self.heim / ".npm" / "_cacache")]
        return C


# ---------- Suchen ----------

def python_installation(k):
    """Mitgeliefertes oder installiertes Python (z. B. in einer App): nicht hinein, nichts darin anfassen."""
    return any(da(k / n) for n in ("python.exe", "pythonw.exe", "pyvenv.cfg", Path("bin") / "python.exe", Path("bin") / "python3",
                                   Path("Lib") / "site-packages", Path("Lib") / "os.py"))


def bau_rest(ordner):
    """build\\ oder dist\\ neben pyproject.toml oder setup.py, nur wenn eindeutig vom Bauen:
    build mit lib/, bdist.*/ oder temp.* darin; dist nur mit .whl und .tar.gz."""
    if ordner.name == "build":
        try:
            K = [k.name for k in ordner.iterdir()]
        except OSError:
            return False
        return bool(K) and all(n == "lib" or n.startswith(("lib.", "bdist.", "temp.", "scripts-")) for n in K)
    if ordner.name == "dist":
        try:
            K = list(ordner.iterdir())
        except OSError:
            return False
        return bool(K) and all(k.is_file() and (k.name.endswith(".whl") or k.name.endswith(".tar.gz")) for k in K)
    return False


def suchen(orte, tage, prozesse):
    grenze = time.time() - tage * 86400
    F, gesehen = [], set()

    def fund(p, grund, wie):
        if p in gesehen or not in_grenze(p, wurzel):
            return
        gesehen.add(p)
        F.append({"pfad": p, "grund": grund, "wie": wie, "bytes": messen(p), "wurzel": wurzel})

    for wurzel in orte.wurzeln():
        for ordner, dirs, files in os.walk(wurzel, onerror=lambda e: None):
            p = Path(ordner)
            tiefe = len(p.relative_to(wurzel).parts)
            namen = set(files)
            projekt_alt = None

            def alt():
                nonlocal projekt_alt
                if projekt_alt is None:
                    projekt_alt = projekt_zuletzt(p) < grenze and not benutzt(p, prozesse)
                return projekt_alt

            for d in list(dirs):
                k = p / d
                if ist_link(k):
                    dirs.remove(d)
                    continue
                if d not in VENV_NAMEN and (d == "site-packages" or python_installation(k)):
                    dirs.remove(d)   # Umgebung mit anderem Namen: nicht anfassen, nicht durchsuchen
                elif d in VENV_NAMEN and da(k / "pyvenv.cfg"):
                    dirs.remove(d)
                    neu = ("pyproject.toml" in namen or "uv.lock" in namen or
                           any(n.startswith("requirements") and n.endswith(".txt") for n in namen))
                    if neu and alt() and zuletzt(k, 1) < grenze and not benutzt(k, prozesse):
                        fund(k, "Python-Umgebung", "uv sync" if "uv.lock" in namen or "pyproject.toml" in namen else "pip install -r requirements.txt")
                elif d == "node_modules":
                    dirs.remove(d)
                    if "package.json" in namen and any(l in namen for l in LOCKS) and alt():
                        fund(k, "node_modules", "npm ci")
                elif d in CACHE_NAMEN:
                    dirs.remove(d)
                    if zuletzt(k, 1) < grenze:
                        fund(k, "Python-Zwischenstand", "von selbst")
                elif d in ("build", "dist") and ("pyproject.toml" in namen or "setup.py" in namen):
                    dirs.remove(d)
                    if bau_rest(k) and zuletzt(k, 2) < grenze:
                        fund(k, "Bau-Rest", "neu bauen")
                elif d.endswith(".egg-info") and ("pyproject.toml" in namen or "setup.py" in namen):
                    dirs.remove(d)
                    if zuletzt(k, 1) < grenze:
                        fund(k, "Bau-Rest", "neu bauen")
                elif d.lower() in NICHT_REIN or d.lower().startswith("onedrive") or tiefe >= TIEFE or \
                        (d == "daten" and da(p / "start.py")):
                    dirs.remove(d)   # Repos-Innereien, Daten der Zentrale, OneDrive und zu Tiefes nicht durchsuchen
    return F


def zwischenspeicher(orte, prozesse):
    F = []
    for name, ordner in orte.caches():
        if not ordner.is_dir():
            continue
        b = messen(ordner)
        if b < CACHE_GRENZE:
            continue
        laeuft = name != "pip" and (werkzeug_laeuft(prozesse, ["uv", "uvx"]) if name == "uv" else
                                    werkzeug_laeuft(prozesse, ["npm"]) or any("npm-cli.js" in z for z in prozesse))
        if laeuft and name == "uv" and not orte.test and shutil.which("uv"):
            # uv läuft (oft dauerhaft, z. B. ein Werkzeug über `uv tool run`): dann nur Ungenutztes, das regelt uv selbst
            F.append({"pfad": ordner, "grund": "Zwischenspeicher uv, nur Ungenutztes (uv läuft gerade)", "wie": "von selbst",
                      "bytes": b, "cache": "uv-prune"})
        elif laeuft:
            F.append({"pfad": ordner, "grund": f"Zwischenspeicher {name} (läuft gerade, bleibt)", "wie": "", "bytes": b, "skip": True})
        else:
            F.append({"pfad": ordner, "grund": f"Zwischenspeicher {name}", "wie": "von selbst", "bytes": b, "cache": name})
    return F


def temp_alt(orte, tage):
    grenze = time.time() - tage * 86400
    F = []
    if not orte.temp.is_dir():
        return F
    try:
        E = list(orte.temp.iterdir())
    except OSError:
        return F
    for k in E:
        if k.name.lower() in ("putzen.log",) or "putz-test" in k.name.lower():
            continue
        # ganzer Baum: eine frisch geänderte Datei tief drin hält den Ordner (die Ordnerzeit wandert nicht immer mit)
        if not ist_link(k) and in_grenze(k, orte.temp) and zuletzt_baum(k) < grenze:
            F.append({"pfad": k, "grund": "Temp", "wie": "von selbst", "bytes": messen(k), "temp": True, "wurzel": orte.temp})
    return F


def nur_melden(orte):
    """Mehrere uv-Programme und von uv installierte Python-Versionen: nur zeigen."""
    M = []
    if orte.test:
        return M
    gefunden = []
    for d in os.environ.get("PATH", "").split(os.pathsep):
        for n in (["uv.exe"] if WIN else ["uv"]):
            f = Path(d) / n
            if d and f.is_file() and f.resolve() not in [g.resolve() for g in gefunden]:
                gefunden.append(f)
    for f in [orte.heim / ".local" / "bin" / ("uv.exe" if WIN else "uv"), orte.heim / ".cargo" / "bin" / ("uv.exe" if WIN else "uv")]:
        if f.is_file() and f.resolve() not in [g.resolve() for g in gefunden]:
            gefunden.append(f)
    if len(gefunden) > 1:
        M.append(f"{len(gefunden)} uv-Programme: " + ", ".join(str(f) for f in gefunden) +
                 ". Eines genügt; welches bleibt, entscheidet der Besitzer (z. B. das neueste, `uv self update`).")
    pd = befehl("uv", "python", "dir", zeit=20)
    if pd and Path(pd).is_dir():
        V = sorted((k for k in Path(pd).iterdir() if k.is_dir() and not k.is_symlink() and k.name.startswith(("cpython", "pypy"))
                    and messen(k) > 1e6), key=lambda k: k.name)
        if len(V) > 1:
            M.append(f"{len(V)} von uv installierte Python-Versionen in {pd}: " +
                     ", ".join(f"{k.name} ({gb(messen(k))})" for k in V) +
                     ". Nicht mehr gebrauchte entfernt `uv python uninstall <version>`, nur nach Ja des Besitzers.")
    return M


# ---------- Ausgabe, Bericht ----------

def zusammenfassen(F, orte):
    """Für die Anzeige: Temp in eine Zeile, Python-Zwischenstände je Projekt in eine Zeile. Entfernt wird trotzdem einzeln."""
    G = {}
    for f in F:
        if f.get("temp"):
            k = ("Temp", orte.temp)
        elif f["grund"] == "Python-Zwischenstand":
            w = f.get("wurzel") or f["pfad"].parent
            teile = f["pfad"].relative_to(w).parts
            k = ("Python-Zwischenstand", w / teile[0] if len(teile) > 1 else w)
        else:
            k = (f["grund"], f["pfad"])
        g = G.setdefault(k, {"grund": k[0], "pfad": k[1], "wie": f["wie"], "bytes": 0, "n": 0})
        g["bytes"] += f["bytes"]
        g["n"] += 1
    Z = sorted(G.values(), key=lambda g: -g["bytes"])
    for g in Z:
        if g["n"] > 1:
            g["grund"] += f" ({g['n']} Stück)" if g["grund"] != "Temp" else f" ({g['n']} Einträge älter als die Grenze)"
    return Z


def tabelle(Z):
    T = ["| Größe | Was | Ort | Kommt wieder mit |", "|---|---|---|---|"]
    for f in Z:
        T.append(f"| {gb(f['bytes'])} | {f['grund']} | `{f['pfad']}` | {f['wie'] or '–'} |")
    return "\n".join(T)


def groesste(orte):
    T = []
    try:
        for k in orte.heim.iterdir():
            if not ist_link(k) and k.is_dir() and k.name.lower() not in (".trash", "$recycle.bin"):
                T.append((messen(k), k))
    except OSError:
        pass
    return sorted(T, reverse=True)[:5]


def client(agent, *args):
    c = HIER.parent / "zentrale_client.py"
    try:
        r = subprocess.run([sys.executable, str(c), "--agent", agent, *args], capture_output=True, text=True, timeout=60,
                           encoding="utf-8", errors="replace", **OHNE_FENSTER)
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except Exception as e:
        return False, str(e)


def schluessel_da(agent):
    ordner = Path(os.environ.get("ZENTRALE_SCHLUESSEL_ORDNER") or Path.home() / ".config" / "zentrale-starter")
    return (ordner / f"{agent}.key").exists()


def bericht(agent, titel, kurz, text, fragen=True):
    if not schluessel_da(agent):
        print(f"Kein Bericht: Schlüssel für „{agent}“ fehlt (py start.py agent-neu {agent}).")
        return
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as t:
        t.write(text)
    args = ["bericht-neu", titel, "--kurz", kurz, "--text-datei", t.name, "--projekt", "Aufräumen"]
    if fragen:
        args += ["--frage", "Soll ich das entfernen?", "--vorschlaege", "Ja, alles|Nur Zwischenspeicher und Temp|Nein"]
    ok, aus = client(agent, *args)
    os.unlink(t.name)
    if ok:
        print("\n".join(z for z in aus.splitlines() if not z.startswith("ACHTUNG")))
    else:
        print(f"Bericht ging nicht: {aus}")


# ---------- Ablauf ----------

def main():
    ap = argparse.ArgumentParser(description="Putzrunde: entfernt nur Neu-Erzeugbares (Standard: nur zeigen).")
    ap.add_argument("--los", action="store_true", help="wirklich entfernen")
    ap.add_argument("--probe", action="store_true", help="nur zeigen (Standard)")
    ap.add_argument("--bericht", action="store_true", help="Probe als Bericht in die Zentrale")
    ap.add_argument("--tage", type=int, default=7, help="so viele Tage unberührt (Standard 7)")
    ap.add_argument("--agent", default=os.environ.get("ZENTRALE_AGENT", "claude"))
    ap.add_argument("--grenze-gb", type=float, default=30, help="darunter Warnung mit den größten Ordnern")
    ap.add_argument("--wurzel", help="Testordner als Benutzerordner")
    a = ap.parse_args()
    los = a.los and not a.probe
    orte = Orte(a.wurzel)
    print(time.strftime("%Y-%m-%d %H:%M"), "Putzrunde", "(entfernt)" if los else "(Probe, ändert nichts)", "in", orte.heim)

    prozesse = laufende()
    F = suchen(orte, a.tage, prozesse) + zwischenspeicher(orte, prozesse) + temp_alt(orte, a.tage)
    weg = sorted([f for f in F if not f.get("skip")], key=lambda f: -f["bytes"])
    bleibt = [f for f in F if f.get("skip")]
    summe = sum(f["bytes"] for f in weg)
    meld = nur_melden(orte)

    Z = zusammenfassen(weg, orte)
    for f in Z:
        print(f"  {gb(f['bytes']):>10}  {f['grund']}: {f['pfad']}")
    for f in bleibt:
        print(f"  {gb(f['bytes']):>10}  {f['grund']}: {f['pfad']}")
    print(f"Summe: {gb(summe)} in {len(weg)} Funden" + ("" if los else " (nichts geändert)"))
    for m in meld:
        print("Nur zur Info: " + m)

    frei_vorher = shutil.disk_usage(orte.heim).free
    entfernt, fehler = 0, []
    if los and weg:
        with P.sperre():
            for f in weg:
                p = f["pfad"]
                if f.get("cache") in ("uv", "uv-prune") and shutil.which("uv") and not orte.test:
                    try:
                        r = subprocess.run(["uv", "cache", "clean" if f["cache"] == "uv" else "prune"], capture_output=True,
                                           text=True, timeout=600, encoding="utf-8", errors="replace", **OHNE_FENSTER)
                        err = "" if r.returncode == 0 else (r.stderr.strip()[:200] or "uv ging nicht")
                    except subprocess.TimeoutExpired:
                        err = "uv brauchte zu lange (wartet auf ein anderes uv), morgen wieder"
                elif f.get("wurzel") and not in_grenze(p, f["wurzel"]):
                    err = "liegt nicht mehr sicher im Suchbereich (Verknüpfung?), bleibt"
                elif f.get("temp") and zuletzt_baum(p) >= time.time() - a.tage * 86400:
                    err = "inzwischen geändert, bleibt"
                else:
                    err = entfernen(p)
                if err and not f.get("temp"):
                    fehler.append(f"{p}: {err}")
                rest = messen(p) if da(p) else 0
                frei = max(0, f["bytes"] - rest)
                entfernt += frei
                if frei:
                    P.eintragen({"art": "geputzt", "von": str(p), "nach": "", "typ": "ordner" if f["grund"] != "Temp" or not da(p) or p.is_dir() else "datei",
                                 "bytes": frei, "grund": f"{f['grund']} (kommt wieder: {f['wie'] or 'von selbst'})"})
        print(f"Entfernt: {gb(entfernt)}" + (f", {len(fehler)} Fehler" if fehler else ""))
        for x in fehler[:10]:
            print("  Fehler: " + x)

    du = shutil.disk_usage(orte.heim)
    print(f"Frei: {gb(frei_vorher)} → {gb(du.free)} von {gb(du.total)}")

    if a.bericht and not los and not weg:
        print("Kein Bericht: Es gibt gerade nichts zu putzen.")
    elif a.bericht and not los:
        text = (f"# Putzrunde: Probe\n\nNur Dinge, die sich von selbst neu erzeugen und seit {a.tage} Tagen unberührt sind. "
                f"Nichts davon ist geändert.\n\n{tabelle(Z)}\n\n**Summe: {gb(summe)}**\n" +
                ("\n## Nur zur Info\n\n" + "\n".join(f"- {m}" for m in meld) + "\n" if meld else ""))
        bericht(a.agent, f"Putzen: {gb(summe)} lassen sich freimachen",
                f"{len(weg)} {'Fund' if len(weg) == 1 else 'Funde'} (Python-Umgebungen, node_modules, Zwischenspeicher, Temp), "
                f"die sich von selbst neu erzeugen. "
                f"Frei sind gerade {gb(du.free)}. Geändert ist noch nichts.", text)

    knapp = du.free < a.grenze_gb * 1e9 or du.free < 0.1 * du.total
    if knapp:
        G = groesste(orte)
        zeilen = "\n".join(f"- `{k}`: {gb(b)}" for b, k in G)
        print("Wenig Platz. Größte Ordner im Benutzerordner:\n" + zeilen)
        if los:
            bericht(a.agent, f"Platte: nur noch {gb(du.free)} frei",
                    f"Die Putzrunde hat {gb(entfernt)} entfernt, mehr geht nur mit dir. Die größten Ordner stehen im Bericht.",
                    f"# Wenig Platz\n\nFrei: {gb(du.free)} von {gb(du.total)}.\n\n## Größte Ordner\n\n{zeilen}\n\n"
                    "Vorschlag: mit dem Agenten durchgehen, was gesichert und in den Papierkorb kann.\n", fragen=False)


if __name__ == "__main__":
    main()
