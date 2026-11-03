#!/usr/bin/env python3
r"""Melder: schickt jede Minute den Zustand dieses Geräts an die Zentrale (Homelab → Geräte).

Läuft unter Windows, macOS und Linux, braucht nur Python 3.6 oder neuer, sonst nichts. Eine einzige Datei: Sie lässt sich
von GitHub holen (https://raw.githubusercontent.com/hadi-yousef/zentrale-starter/main/melder/melder.py) oder per USB-Stick
kopieren. Die Zentrale nimmt von anderen Geräten nur Tailscale an (docs/HOMELAB.md).

  python3 melder.py einrichten --zentrale http://<Tailscale-Adresse der Zentrale>:8090 --name "MacBook-Air-2015" --schluessel-datei geraet-macbook-air-2015.key
  python3 melder.py --zeigen        zeigt, was gemeldet würde (schickt nichts)
  python3 melder.py --einmal        meldet einmal und zeigt die Antwort
  python3 melder.py                 meldet jede Minute (für den Autostart)
  python3 melder.py autostart       zeigt die fertigen Befehle für den Autostart auf diesem System
  (Windows: py statt python3, im Autostart pyw = ohne Fenster)

Gemeldet werden: Name, Betriebssystem, Modell, Laufzeit, Prozessor-Last, Arbeitsspeicher, Laufwerke mit freiem Platz und
Größe des Papierkorbs, Akku, Temperatur (wo ohne Administrator lesbar), Adresse im Heimnetz, Tailscale an/aus, bei Linux
ausstehende Updates und Dienste (systemd, Docker). Keine Dateinamen, keine Inhalte, keine Passwörter.
Einstellungen: ~/.config/zentrale-melder/melder.json (Windows: %USERPROFILE%\.config\zentrale-melder\melder.json).
"""
import getpass
import json
import os
import platform
import re
import shutil
import socket
import string
import subprocess
import sys
import time
import urllib.request

FASSUNG = 1   # gleich wie MELDER_FASSUNG in zentrale/geraete.py
WIN, MAC = os.name == "nt", sys.platform == "darwin"
ART = "windows" if WIN else "mac" if MAC else "linux"
ORDNER = os.path.join(os.path.expanduser("~"), ".config", "zentrale-melder")
EINST = os.path.join(ORDNER, "melder.json")
OHNE_FENSTER = 0x08000000 if WIN else 0   # CREATE_NO_WINDOW: unter pyw blitzen keine Konsolenfenster auf
_cache = {}


def befehl(args, zeit=20):
    """Programm ausführen, Ausgabe als Text, bei Fehler ""."""
    try:
        r = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, timeout=zeit,
                           creationflags=OHNE_FENSTER)
        return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def selten(name, sekunden, fn):
    """Teure Abfragen (Ordnergrößen, Updates, Akkuzustand) nur alle paar Minuten oder Stunden."""
    t, v = _cache.get(name, (0, None))
    if time.time() - t > sekunden:
        try:
            v = fn()
        except Exception:
            v = None
        _cache[name] = (time.time(), v)
    return v


def _junction(p):
    """Windows-Verbindung: os.walk ginge sonst hinein, in jeder Python-Fassung. OneDrive-Ordner zählen nicht dazu."""
    try:
        return getattr(os.lstat(p), "st_reparse_tag", 0) == 0xA0000003
    except OSError:
        return False


def ordnergroesse(p, grenze=300000):
    """Größe eines Ordners (für den Papierkorb), höchstens grenze Dateien zählen."""
    summe, n = 0, 0
    for w, unter, dateien in os.walk(p):
        unter[:] = [x for x in unter if not _junction(os.path.join(w, x))]
        for d in dateien:
            try:
                summe += os.lstat(os.path.join(w, d)).st_size
            except OSError:
                pass
            n += 1
            if n > grenze:
                return summe
    return summe


def papierkorb(wurzel):
    p = os.path.join(wurzel, "Papierkorb")
    return selten("pk:" + p, 1800, lambda: ordnergroesse(p)) if os.path.isdir(p) else None


def ip_heimnetz():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))   # schickt nichts, wählt nur die Netzwerkkarte
        a = s.getsockname()[0]
        s.close()
        return [a] if not a.startswith("127.") else []
    except OSError:
        return []


def tailscale():
    prog = shutil.which("tailscale")
    for p in (r"C:\Program Files\Tailscale\tailscale.exe", "/Applications/Tailscale.app/Contents/MacOS/Tailscale"):
        if not prog and os.path.exists(p):
            prog = p
    if not prog:
        return None
    ip = befehl([prog, "ip", "-4"], 8).strip().splitlines()
    return {"an": bool(ip), "ip": ip[0] if ip else ""}


# ---------- Windows ----------

PS_WIN = r"""
$ErrorActionPreference = 'SilentlyContinue'
$os = Get-CimInstance Win32_OperatingSystem
$cs = Get-CimInstance Win32_ComputerSystem
$cpu = @(Get-CimInstance Win32_Processor)
$lw = @(Get-CimInstance Win32_LogicalDisk | Where-Object { $_.DriveType -in 2,3,4 } | ForEach-Object {
  @{ lw = $_.DeviceID; name = $_.VolumeName; gesamt = [int64]$_.Size; frei = [int64]$_.FreeSpace; fs = $_.FileSystem; typ = [int]$_.DriveType } })
$b = Get-CimInstance Win32_Battery | Select-Object -First 1
@{
  system = "$($os.Caption) $($os.Version)"; boot = $os.LastBootUpTime.ToString('o')
  ram_gesamt = [int64]$os.TotalVisibleMemorySize * 1024; ram_frei = [int64]$os.FreePhysicalMemory * 1024
  modell = "$($cs.Manufacturer) $($cs.Model)"; cpu_name = $cpu[0].Name; kerne = ($cpu | Measure-Object NumberOfLogicalProcessors -Sum).Sum
  cpu = ($cpu | Measure-Object LoadPercentage -Average).Average
  laufwerke = $lw
  akku = if ($b) { @{ prozent = $b.EstimatedChargeRemaining; netzteil = ($b.BatteryStatus -in 2,6,7,8,9) } } else { $null }
} | ConvertTo-Json -Depth 4 -Compress
"""
PS_AKKU = r"""
$ErrorActionPreference = 'SilentlyContinue'
$z = (Get-CimInstance -Namespace root\wmi BatteryCycleCount | Select-Object -First 1).CycleCount
$v = (Get-CimInstance -Namespace root\wmi BatteryFullChargedCapacity | Select-Object -First 1).FullChargedCapacity
$d = (Get-CimInstance -Namespace root\wmi BatteryStaticData | Select-Object -First 1).DesignedCapacity
@{ zyklen = $z; voll = $v; design = $d } | ConvertTo-Json -Compress
"""


def windows():
    d = json.loads(befehl(["powershell", "-NoProfile", "-NonInteractive", "-Command", PS_WIN], 60) or "{}")
    lw = d.get("laufwerke") or []
    lw = [lw] if isinstance(lw, dict) else lw
    m = {"system": (d.get("system") or "").replace("Microsoft ", ""), "modell": (d.get("modell") or "").strip(), "cpu_name": (d.get("cpu_name") or "").strip(),
         "kerne": d.get("kerne"), "cpu": d.get("cpu"), "ram_gesamt": d.get("ram_gesamt"),
         "ram_belegt": (d.get("ram_gesamt") or 0) - (d.get("ram_frei") or 0) if d.get("ram_gesamt") else None,
         "laufwerke": [{"lw": l.get("lw"), "name": l.get("name") or "", "gesamt": l.get("gesamt"), "frei": l.get("frei"), "fs": l.get("fs") or "",
                        "art": {2: "wechselbar", 4: "netz"}.get(l.get("typ"), "intern"),
                        "papierkorb": papierkorb((l.get("lw") or "") + "\\") if l.get("typ") != 4 else None} for l in lw if l.get("gesamt")]}
    try:
        boot = d.get("boot") or ""
        from datetime import datetime
        t = datetime.strptime(re.sub(r"\.\d+", "", boot)[:19], "%Y-%m-%dT%H:%M:%S")
        m["seit"] = int(time.time() - time.mktime(t.timetuple()))
    except (ValueError, TypeError):
        pass
    a = d.get("akku")
    if a:
        z = selten("akku", 21600, lambda: json.loads(befehl(["powershell", "-NoProfile", "-NonInteractive", "-Command", PS_AKKU], 30) or "{}")) or {}
        m["akku"] = {"prozent": a.get("prozent"), "netzteil": a.get("netzteil"), "zyklen": z.get("zyklen"),
                     "kapazitaet": round(100.0 * z["voll"] / z["design"], 1) if z.get("voll") and z.get("design") else None}
    return m


# ---------- macOS ----------

def mac():
    sc = lambda k: befehl(["sysctl", "-n", k]).strip()
    m = {"system": "macOS " + befehl(["sw_vers", "-productVersion"]).strip(), "modell": sc("hw.model"), "cpu_name": sc("machdep.cpu.brand_string")}
    try:
        m["kerne"] = int(sc("hw.ncpu"))
        m["ram_gesamt"] = int(sc("hw.memsize"))
        boot = re.search(r"sec = (\d+)", sc("kern.boottime"))
        m["seit"] = int(time.time()) - int(boot.group(1)) if boot else None
    except ValueError:
        pass
    vm = befehl(["vm_stat"])
    seite = int((re.search(r"page size of (\d+)", vm) or [0, 4096])[1])
    wert = lambda k: int((re.search(r'"?' + k + r'"?:\s+(\d+)', vm) or [0, 0])[1])
    if m.get("ram_gesamt"):
        m["ram_belegt"] = (wert("Pages active") + wert("Pages wired down") + wert("Pages occupied by compressor")) * seite
    last = [float(x) for x in re.findall(r"[\d.]+", befehl(["ps", "-A", "-o", "%cpu="]))]
    if m.get("kerne"):
        m["cpu"] = min(100.0, sum(last) / m["kerne"])
    wurzeln = ["/"] + [os.path.join("/Volumes", v) for v in (os.listdir("/Volumes") if os.path.isdir("/Volumes") else [])]
    netz = {z.split(" on ", 1)[1].split(" (")[0] for z in befehl(["mount"]).splitlines()
            if " on " in z and re.search(r"\((smbfs|afpfs|nfs|webdav|cifs)", z)}
    L, gesehen = [], set()
    for w in wurzeln:
        try:
            if not os.path.ismount(w) or os.path.realpath(w) == "/" and w != "/":
                continue
            st, du = os.statvfs(w), shutil.disk_usage(w)
        except OSError:
            continue
        if (st.f_fsid if hasattr(st, "f_fsid") else w) in gesehen or du.total < 1e9 or "TimeMachine" in w or w.startswith("/Volumes/.timemachine"):
            continue
        gesehen.add(st.f_fsid if hasattr(st, "f_fsid") else w)
        heim = os.path.expanduser("~") if w == "/" else w
        art = "intern" if w == "/" else "netz" if w in netz else "wechselbar"
        L.append({"lw": w, "name": "Macintosh HD" if w == "/" else os.path.basename(w), "gesamt": du.total, "frei": du.free,
                  "art": art, "papierkorb": papierkorb(heim) if art != "netz" else None})
    m["laufwerke"] = L
    b = befehl(["pmset", "-g", "batt"])
    p = re.search(r"(\d+)%", b)
    if p:
        m["akku"] = {"prozent": int(p.group(1)), "netzteil": "AC Power" in b, "laedt": "charging" in b and "discharging" not in b}
        z = selten("akku", 21600, lambda: befehl(["system_profiler", "SPPowerDataType"], 60)) or ""
        c = re.search(r"Cycle Count:\s*(\d+)", z)
        k = re.search(r"Condition:\s*(.+)", z)
        mx = re.search(r"Maximum Capacity:\s*(\d+)%", z)
        m["akku"].update(zyklen=int(c.group(1)) if c else None, zustand=k.group(1).strip() if k else "", kapazitaet=int(mx.group(1)) if mx else None)
    return m


# ---------- Linux ----------

def _lies(p, standard=""):
    try:
        with open(p) as f:
            return f.read()
    except OSError:
        return standard


def _cpu_jiffies():
    z = _lies("/proc/stat").splitlines()
    w = [int(x) for x in z[0].split()[1:]] if z else []
    return (sum(w), w[3] + (w[4] if len(w) > 4 else 0)) if w else (0, 0)


FS_ECHT = {"ext2", "ext3", "ext4", "xfs", "btrfs", "vfat", "exfat", "ntfs", "ntfs3", "fuseblk", "f2fs", "zfs", "apfs", "hfsplus"}


def linux():
    os_rel = dict(re.findall(r'^(\w+)="?([^"\n]*)"?', _lies("/etc/os-release"), re.M))
    m = {"system": os_rel.get("PRETTY_NAME", "Linux") + ", Kernel " + platform.release().split("-")[0],
         "modell": " ".join(x for x in (_lies("/sys/class/dmi/id/sys_vendor").strip(), _lies("/sys/class/dmi/id/product_name").strip()) if x),
         "cpu_name": (re.search(r"model name\s*:\s*(.+)", _lies("/proc/cpuinfo")) or [0, ""])[1].strip(), "kerne": os.cpu_count()}
    try:
        m["seit"] = int(float(_lies("/proc/uptime", "0").split()[0]))
    except (ValueError, IndexError):
        pass
    a1 = _cpu_jiffies()
    time.sleep(1)
    a2 = _cpu_jiffies()
    if a2[0] > a1[0]:
        m["cpu"] = round(100.0 * (1 - (a2[1] - a1[1]) / (a2[0] - a1[0])), 1)
    mi = {k: int(v) * 1024 for k, v in re.findall(r"^(\w+):\s+(\d+) kB", _lies("/proc/meminfo"), re.M)}
    if mi.get("MemTotal"):
        m["ram_gesamt"], m["ram_belegt"] = mi["MemTotal"], mi["MemTotal"] - mi.get("MemAvailable", mi.get("MemFree", 0))
    L, gesehen = [], set()
    for z in _lies("/proc/mounts").splitlines():
        t = z.split()
        if len(t) < 3 or t[2] not in FS_ECHT or t[0] in gesehen or t[1].startswith(("/snap", "/boot/efi", "/var/lib/docker")):
            continue
        try:
            du = shutil.disk_usage(t[1].replace("\\040", " "))
        except OSError:
            continue
        if du.total < 1e9:
            continue
        gesehen.add(t[0])
        w = t[1].replace("\\040", " ")
        L.append({"lw": w, "name": "Systemplatte" if w == "/" else os.path.basename(w), "gesamt": du.total, "frei": du.free, "fs": t[2],
                  "art": "wechselbar" if w.startswith(("/media", "/mnt", "/run/media")) else "intern",
                  "papierkorb": papierkorb(os.path.expanduser("~") if w == "/" else w)})
    m["laufwerke"] = L
    ps = "/sys/class/power_supply"
    for n in sorted(os.listdir(ps)) if os.path.isdir(ps) else []:
        if n.startswith("BAT"):
            q = lambda k: _lies(os.path.join(ps, n, k)).strip()
            voll, design = q("energy_full") or q("charge_full"), q("energy_full_design") or q("charge_full_design")
            netz = any(_lies(os.path.join(ps, x, "online")).strip() == "1" for x in os.listdir(ps) if x.startswith(("AC", "ADP")))
            m["akku"] = {"prozent": int(q("capacity") or 0), "netzteil": netz, "laedt": q("status") == "Charging",
                         "zyklen": int(q("cycle_count")) if q("cycle_count").isdigit() and q("cycle_count") != "0" else None,
                         "kapazitaet": round(100.0 * int(voll) / int(design), 1) if voll.isdigit() and design.isdigit() and int(design) else None}
            break
    T = []
    for z in (os.listdir("/sys/class/thermal") if os.path.isdir("/sys/class/thermal") else []):
        v = _lies("/sys/class/thermal/%s/temp" % z).strip()
        if z.startswith("thermal_zone") and v.lstrip("-").isdigit() and 0 < int(v) < 150000:
            T.append(int(v) / 1000.0)
    m["temp"] = max(T) if T else None
    if shutil.which("systemctl"):
        fehler = [z.split()[0] for z in befehl(["systemctl", "--failed", "--no-legend", "--plain"]).splitlines() if z.strip()]
        laufend = len([z for z in befehl(["systemctl", "list-units", "--type=service", "--state=running", "--no-legend", "--plain"]).splitlines() if z.strip()])
        m["dienste"] = {"laufend": laufend, "fehler": fehler}
    if shutil.which("docker"):
        C = []
        for z in befehl(["docker", "ps", "-a", "--format", "{{json .}}"], 15).splitlines():
            try:
                c = json.loads(z)
            except ValueError:
                continue
            C.append({"name": c.get("Names", ""), "bild": c.get("Image", ""), "zustand": c.get("Status", ""), "laeuft": c.get("State") == "running"})
        m["docker"] = C
    if shutil.which("apt"):
        m["updates"] = selten("updates", 21600, lambda: len([z for z in befehl(["apt", "list", "--upgradable"], 60).splitlines() if "upgradable" in z]))
    m["neustart"] = os.path.exists("/var/run/reboot-required")
    return m


# ---------- Meldung zusammenstellen und schicken ----------

def zustand(name):
    m = windows() if WIN else mac() if MAC else linux()
    if MAC:   # Temperatur gibt macOS ohne Administrator nicht her
        m["temp"] = None
    m.update(melder=FASSUNG, art=ART, name=name or socket.gethostname(), rechnername=socket.gethostname(), ip=ip_heimnetz(), tailscale=tailscale())
    return m


def einstellungen():
    try:
        with open(EINST, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        sys.exit("Noch nicht eingerichtet: python3 melder.py einrichten --zentrale http://<adresse>:8090 --name <Name> --schluessel-datei <datei>")


def schicken(e, m):
    r = urllib.request.Request(e["zentrale"].rstrip("/") + "/api/geraete/melden", data=json.dumps(m).encode("utf-8"), method="POST",
                               headers={"Authorization": "Bearer " + e["schluessel"], "Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=20) as a:
        return json.loads(a.read().decode("utf-8"))


def einrichten(zentrale, name, datei):
    if datei:
        with open(datei, encoding="utf-8") as f:
            s = f.read().strip()
    else:
        s = getpass.getpass("Schlüssel des Geräts (aus der Datei geraet-….key, wird nicht angezeigt): ").strip()
    if not s:
        sys.exit("Kein Schlüssel.")
    e = {"zentrale": zentrale.rstrip("/"), "name": name, "schluessel": s}
    try:
        a = schicken(e, zustand(name))
    except Exception as x:
        sys.exit("Die Zentrale nimmt die Meldung nicht an: %s\nLäuft sie mit --heimnetz? Ist es die Tailscale-Adresse (das normale Heimnetz weist sie ab)? Passt der Schlüssel?" % x)
    os.makedirs(ORDNER, exist_ok=True)
    with open(EINST, "w", encoding="utf-8") as f:
        json.dump(e, f)
    try:
        os.chmod(EINST, 0o600)
    except OSError:
        pass
    print("Eingerichtet: „%s“ meldet an %s (Gerät %s). Einstellungen: %s" % (name, e["zentrale"], a.get("id"), EINST))
    if datei:
        print("Die Schlüsseldatei %s wird nicht mehr gebraucht: in den Papierkorb legen." % datei)
    print("Jetzt den Autostart einrichten: python3 melder.py autostart")


def autostart():
    py, ich = sys.executable, os.path.abspath(__file__)
    if WIN:
        pyw = py.replace("python.exe", "pythonw.exe") if py.lower().endswith("python.exe") else py
        print("Windows (PowerShell, als dieser Benutzer):\n"
              "  $a = New-ScheduledTaskAction -Execute \"%s\" -Argument '\"%s\"'\n"
              "  $t = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME\n"
              "  $s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)\n"
              "  Register-ScheduledTask -TaskName \"Zentrale Melder\" -Action $a -Trigger $t -Settings $s\n"
              "  Start-ScheduledTask -TaskName \"Zentrale Melder\"\n"
              "Rückgängig: Unregister-ScheduledTask -TaskName \"Zentrale Melder\"" % (pyw, ich))
    elif MAC:
        plist = os.path.expanduser("~/Library/LaunchAgents/de.zentrale-starter.melder.plist")
        print("macOS (Terminal):\n  cat > %s <<'ENDE'\n"
              "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">\n"
              "<plist version=\"1.0\"><dict><key>Label</key><string>de.zentrale-starter.melder</string>\n"
              "<key>ProgramArguments</key><array><string>%s</string><string>%s</string></array>\n"
              "<key>RunAtLoad</key><true/><key>KeepAlive</key><true/>\n"
              "<key>StandardErrorPath</key><string>%s</string></dict></plist>\nENDE\n"
              "  launchctl load -w %s\n"
              "Rückgängig: launchctl unload -w %s und die Datei in den Papierkorb." % (plist, py, ich, os.path.join(ORDNER, "melder.log"), plist, plist))
    else:
        print("Linux (systemd, für alle Werte als System-Dienst mit sudo):\n"
              "  sudo tee /etc/systemd/system/zentrale-melder.service <<'ENDE'\n"
              "[Unit]\nDescription=Zentrale Melder\nAfter=network-online.target\n\n"
              "[Service]\nUser=%s\nExecStart=%s %s\nRestart=always\nRestartSec=30\n\n[Install]\nWantedBy=multi-user.target\nENDE\n"
              "  sudo systemctl daemon-reload && sudo systemctl enable --now zentrale-melder\n"
              "Docker-Container sieht der Melder nur, wenn dieser Benutzer in der Gruppe docker ist.\n"
              "Rückgängig: sudo systemctl disable --now zentrale-melder" % (getpass.getuser(), py, ich))


def schleife():
    e = einstellungen()
    if sys.stdout is None or (WIN and os.path.basename(sys.executable).lower().startswith("pythonw")):
        os.makedirs(ORDNER, exist_ok=True)
        sys.stdout = sys.stderr = open(os.path.join(ORDNER, "melder.log"), "a", encoding="utf-8", buffering=1)
    fehler = 0
    while True:
        start = time.time()
        try:
            schicken(e, zustand(e.get("name")))
            fehler = 0
        except Exception as x:
            fehler += 1
            if fehler in (1, 10) or fehler % 60 == 0:   # nicht jede Minute ins Protokoll
                print(time.strftime("%Y-%m-%d %H:%M"), "Meldung klappt nicht:", x, flush=True)
        time.sleep(max(5, 60 - (time.time() - start)))


def main():
    a = sys.argv[1:]
    if a[:1] == ["einrichten"]:
        import argparse
        ap = argparse.ArgumentParser(prog="melder.py einrichten")
        ap.add_argument("--zentrale", required=True, help="Adresse der Zentrale, z. B. http://<Tailscale-Adresse>:8090 oder http://heimserver:8090")
        ap.add_argument("--name", required=True, help="Name des Geräts, wie er in der Zentrale stehen soll")
        ap.add_argument("--schluessel-datei", help="Datei geraet-….key (sonst wird der Schlüssel abgefragt)")
        x = ap.parse_args(a[1:])
        return einrichten(x.zentrale, x.name, x.schluessel_datei)
    if a[:1] == ["autostart"]:
        return autostart()
    if "--zeigen" in a:
        e = {}
        if os.path.exists(EINST):
            with open(EINST, encoding="utf-8") as f:
                e = json.load(f)
        return print(json.dumps(zustand(e.get("name")), ensure_ascii=False, indent=1))
    if "--einmal" in a:
        e = einstellungen()
        return print(json.dumps(schicken(e, zustand(e.get("name"))), ensure_ascii=False))
    if a and a[0] in ("-h", "--help", "hilfe"):
        return print(__doc__)
    schleife()


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    main()
