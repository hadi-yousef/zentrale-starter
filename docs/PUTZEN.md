# Putzen: Platz schaffen, ohne etwas Wichtiges anzufassen

Für Agenten. Auf vielen Rechnern liegt viel Müll, der sich von selbst neu erzeugt: Python-Umgebungen (`.venv`) alter
Projekte, `node_modules`, die Zwischenspeicher von uv, pip und npm, alte Dateien in `%TEMP%`. Das räumt
`aufraeumen\putzen.py` weg. Es fasst nur das an und nur, wenn es seit 7 Tagen unberührt ist (Regel „Sichern und
Aufräumen“ in `REGELN.md`). Alles andere bleibt Sache des Plans aus Phase 3 und kommt in den Papierkorb.

| Was | Wann weg | Kommt wieder mit |
|---|---|---|
| `.venv`, `venv` neben `pyproject.toml`, `uv.lock` oder `requirements*.txt` | Projekt 7 Tage unberührt, nichts daraus läuft | `uv sync` oder `pip install -r requirements.txt` |
| `node_modules` neben `package.json` **mit** Lockfile | Projekt 7 Tage unberührt | `npm ci` (bzw. yarn, pnpm) |
| `__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache` | 7 Tage unberührt | von selbst |
| `build\`, `dist\`, `*.egg-info` neben `pyproject.toml`/`setup.py`, nur eindeutige Bau-Reste | 7 Tage unberührt | neu bauen |
| Zwischenspeicher von uv, pip, npm | größer als 2 GB | von selbst beim nächsten Installieren |
| Einträge in `%TEMP%` | älter als 7 Tage, gesperrte bleiben | – |

**Nur gemeldet, nie entfernt:** mehrere `uv`-Programme auf dem Rechner und von uv installierte Python-Versionen.
Welche bleiben, entscheidet der Besitzer. Danach `uv python uninstall <version>` bzw. das überzählige `uv.exe` in den
Papierkorb, beides nur nach seinem Ja.

**Nie angefasst:** Downloads, Dokumente, Bilder, Repos (`.git`), Daten der Zentrale, OneDrive, Python in Apps,
Verknüpfungen, alles außerhalb des Benutzerordners außer `%TEMP%`. Läuft etwas aus einem Projekt (z. B. ein Server aus
seiner `.venv`), bleibt das Projekt. Läuft uv gerade dauerhaft (z. B. ein Werkzeug über `uv tool run`), wird nur
Ungenutztes aus seinem Zwischenspeicher entfernt (`uv cache prune`). Administratorrechte braucht es nicht.

## 1. Probe (ändert nichts)

```powershell
cd $HOME\Projekte\zentrale-starter
py aufraeumen\putzen.py
```

Zeig dem Besitzer das Ergebnis als Tabelle (Größe, Was, Ort, kommt wieder mit) und die Summe. Gleichartiges steht je
Projekt in einer Zeile, zum Beispiel „Python-Zwischenstand (14 Stück)“. Ist er nicht im Chat, schickt
`py aufraeumen\putzen.py --bericht --agent claude` dasselbe als Bericht mit der Frage „Soll ich das entfernen?“.

Fällt dir in der Liste etwas auf, das er gerade braucht (ein Projekt, an dem er heute arbeiten will), nimm es nicht mit:
Dann vorher einmal etwas in dem Projekt öffnen oder speichern, oder die Putzrunde mit `--tage 30` laufen lassen.

## 2. Putzen (nach Ja)

```powershell
py aufraeumen\putzen.py --los
```

Jede Entfernung steht im Aufräum-Protokoll (`aufraeumen\protokoll.jsonl`, Art `geputzt`, mit Größe und womit es
wiederkommt). Auf der Seite „Papierkorb“ erscheint es nicht, weil es nicht im Papierkorb liegt. Zurückholen braucht es
nicht: Beim nächsten `uv sync` oder `npm ci` ist es wieder da. Sag dem Besitzer danach: wie viel frei wurde, frei vorher
und nachher.

Reicht der Platz danach immer noch nicht (unter 30 GB oder unter 10 % frei), nennt es die fünf größten Ordner und schickt
mit `--los` einen Bericht. Dann geht es mit `aufraeumen\inventur.py` und einem Plan weiter (Phase 2 und 3 in `AGENTS.md`).

## 3. Tägliche Putzrunde (nach Ja)

Frage: „Soll das jeden Tag von selbst laufen? Es entfernt nur, was sich neu erzeugt, und meldet sich, wenn der Platz knapp wird.“
Nach Ja, in PowerShell im Ordner der Zentrale:

```powershell
$ordner = (Get-Location).Path                          # z. B. C:\Users\<Name>\Projekte\zentrale-starter
$py = (Get-Command pyw.exe -ErrorAction SilentlyContinue).Source
if (-not $py) { $py = (Get-Command pythonw.exe).Source }   # pyw/pythonw = ohne Konsolenfenster
$aktion = New-ScheduledTaskAction -Execute $py -Argument "`"$ordner\aufraeumen\putzen.py`" --los" -WorkingDirectory $ordner
$ausloeser = New-ScheduledTaskTrigger -Daily -At 12:30
$einst = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)
Register-ScheduledTask -TaskName "Zentrale Putzen" -Action $aktion -Trigger $ausloeser -Settings $einst `
    -Description "Putzrunde: entfernt nur, was sich neu erzeugt (aufraeumen\putzen.py)"
```

`-StartWhenAvailable` holt die Runde nach, wenn der Rechner um 12:30 aus war.

Prüfen:
```powershell
Start-ScheduledTask -TaskName "Zentrale Putzen"
Start-Sleep 30
Get-ScheduledTaskInfo -TaskName "Zentrale Putzen"        # LastTaskResult 0 = gut
Get-Content aufraeumen\putzen.log -Tail 20               # was die Runde getan hat
```

Rückgängig: `Unregister-ScheduledTask -TaskName "Zentrale Putzen"` (entfernt nur die Aufgabe).

Mac: launchd mit `python3 …/aufraeumen/putzen.py --los` täglich (wie in `docs/AUTOSTART.md`, Abschnitt Mac), Linux: ein
Eintrag in `crontab -e`, z. B. `30 12 * * * python3 ~/Projekte/zentrale-starter/aufraeumen/putzen.py --los`.

## Mehr Platz, nur mit Freigabe

| Was | Wie |
|---|---|
| Windows-Datenträgerbereinigung | Der Besitzer startet `cleanmgr` selbst („Systemdateien bereinigen“ braucht Administratorrechte). Du erklärst nur, was die Haken bedeuten. |
| Große Dateien finden | `py aufraeumen\inventur.py` (nur lesen), dann im Plan entscheiden. |
| Downloads sichten | Liste aus der Inventur zeigen (alte Installer, doppelte Dateien), nach Ja mit `aufraeumen\verschieben.py --papierkorb`. Nie löschen. |
| Überzählige uv-Programme, alte uv-Pythons | aus „Nur zur Info“ der Probe, nach Ja wie oben beschrieben |
