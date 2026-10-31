# Autostart

Die Zentrale soll nach jeder Anmeldung von selbst laufen, ohne Fenster. Vorher einmal von Hand `py start.py` starten,
damit der Schlüssel des Besitzers angelegt ist. Ohne Fenster schreibt die Zentrale ihre Meldungen nach `daten\zentrale.log`.

## Windows: Aufgabenplanung

In PowerShell (als normaler Benutzer), im Ordner der Zentrale:

```powershell
$ordner = (Get-Location).Path                          # z. B. C:\Users\<Name>\Projekte\zentrale-starter
$py = (Get-Command pyw.exe -ErrorAction SilentlyContinue).Source
if (-not $py) { $py = (Get-Command pythonw.exe).Source }   # pyw/pythonw = ohne Konsolenfenster
$aktion = New-ScheduledTaskAction -Execute $py -Argument "`"$ordner\start.py`"" -WorkingDirectory $ordner
$ausloeser = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$einst = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName "Zentrale" -Action $aktion -Trigger $ausloeser -Settings $einst `
    -Description "Zentrale auf http://127.0.0.1:8090"
```

Prüfen:
```powershell
Start-ScheduledTask -TaskName "Zentrale"
Start-Sleep 3
Invoke-RestMethod http://127.0.0.1:8090/api/lebt        # zeigt ok = True
Get-ScheduledTaskInfo -TaskName "Zentrale"              # LastTaskResult 0 = gut
```

- Läuft die Zentrale schon in einem Fenster, erst dort beenden (Strg+C), sonst ist der Port belegt.
- Meldet `Register-ScheduledTask` „Zugriff verweigert“: PowerShell einmal „Als Administrator ausführen“ und dieselben
  Befehle noch einmal. Die Aufgabe läuft trotzdem nur als dieser Benutzer.
- Python aus dem Microsoft Store: Dort findet `Get-Command` manchmal nur einen Platzhalter unter `WindowsApps`, der aus der
  Aufgabenplanung nicht startet. Dann Python von python.org nehmen.
- Rückgängig: `Unregister-ScheduledTask -TaskName "Zentrale"` (entfernt nur die Aufgabe, keine Daten).
- Grafisch geht dasselbe in der „Aufgabenplanung“ (taskschd.msc): Aufgabe erstellen, Trigger „Bei Anmeldung“,
  Aktion „Programm starten“ = `pyw.exe`, Argument = `start.py`, Starten in = Ordner der Zentrale.

## Mac: launchd (kurz)

`~/Library/LaunchAgents/zentrale-starter.plist` mit eigenem Pfad anlegen:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>zentrale-starter</string>
  <key>ProgramArguments</key><array><string>/usr/bin/python3</string><string>start.py</string></array>
  <key>WorkingDirectory</key><string>/Users/NAME/Projekte/zentrale-starter</string>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/Users/NAME/Projekte/zentrale-starter/daten/zentrale.log</string>
  <key>StandardErrorPath</key><string>/Users/NAME/Projekte/zentrale-starter/daten/zentrale.log</string>
</dict></plist>
```
Laden: `launchctl load ~/Library/LaunchAgents/zentrale-starter.plist`, entladen mit `unload`.

## Linux: systemd --user (kurz)

`~/.config/systemd/user/zentrale.service`:

```ini
[Unit]
Description=Zentrale (127.0.0.1:8090)

[Service]
WorkingDirectory=%h/Projekte/zentrale-starter
ExecStart=/usr/bin/python3 start.py
Restart=on-failure

[Install]
WantedBy=default.target
```
Einschalten: `systemctl --user daemon-reload && systemctl --user enable --now zentrale`. Log: `journalctl --user -u zentrale`.

**Als Server im Homelab** (läuft ohne Anmeldung, auch für andere Geräte): `ExecStart=/usr/bin/python3 start.py --heimnetz`
und einmal `sudo loginctl enable-linger $USER`, damit der Dienst nach dem Hochfahren startet, ohne dass sich jemand
anmeldet. Ablauf und Firewall: `docs/HOMELAB.md`.
