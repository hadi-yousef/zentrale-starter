# Homelab einrichten: alte Laptops und Rechner nach System

Für Agenten. Du nimmst den Besitzer an die Hand: **Du machst jeden Schritt selbst**, er sagt nur Ja oder Nein und tut die
wenigen Dinge, die nur er tun kann (Anmelden bei Diensten, Linux installieren, Platten formatieren, Passwörter).
Schick ihm keine Befehle zum Abtippen. Jeder Schritt endet mit seinem Ja, ohne Ja fängst du den nächsten nicht an.
Trag den Auftrag als Wunsch ein (`wunsch "Homelab einrichten" --prio hoch --gruppe Homelab`) und halte den Stand je
Schritt als Notiz fest.

**Das System:**

| Teil | Wie |
|---|---|
| Ein Gerät läuft immer | der **Server**: trägt die Zentrale, die Freigabe „Ablage“ und die Sicherung. Am besten Linux. |
| Jedes andere Gerät | hat einen **Melder** (`melder/melder.py`), der jede Minute meldet: Prozessor, Speicher, Platten, Akku, Netz, Dienste. |
| Zugriff von unterwegs | über **Tailscale** (Client Open Source, BSD-3-Clause). Anmelden macht der Besitzer selbst. |
| Ablage | eine Freigabe **Ablage** auf dem Server, für alles, was mehrere Geräte brauchen. |
| Sicherung | jede Nacht mit **restic** (Open Source, BSD-2-Clause), versioniert, auf eine zweite Platte. |
| Papierkorb | auf jeder Platte genau einer (`X:\Papierkorb`, `~/Papierkorb`). Leeren nur der Besitzer. |

In der Zentrale steht alles unter **Homelab**: Geräte (Karten mit Ringen und Warnungen), Dienste (Linux), Netzwerk,
Speicher (alle Laufwerke mit Papierkorb), Papierkorb. Bilder: `docs/REFERENZ.md`, 15 bis 17.

| Schritt | Was | Ändert etwas? |
|---|---|---|
| 1 | Geräte erfassen | nur Notizen |
| 2 | Zentrale im Heimnetz erreichbar machen | Start-Option, eine Firewall-Regel, nach Ja |
| 3 | Melder auf jedem Gerät | eine Datei und ein Autostart je Gerät, nach Ja |
| 4 | Entscheiden: welches Gerät wird der Server? | nein, nur Vorschlag |
| 5 | Server aufsetzen und die Zentrale umziehen | ja, Schritt für Schritt nach Ja |
| 6 | Tailscale | der Besitzer meldet sich an |
| 7 | Freigabe „Ablage“ und nächtliche Sicherung | nach Ja |
| 8 | Putzen auf jedem Gerät | nach Ja |

## 1. Geräte erfassen

Frag den Besitzer, welche Geräte er hat (auch die in der Schublade), und schau sie dir mit ihm an. Je Gerät eine Notiz
`Geräte/<Name>.md`: Modell und Baujahr, Prozessor, Arbeitsspeicher, Platte (Art und Größe, frei), Akku (Zyklen, Zustand),
Betriebssystem, wofür es heute genutzt wird, was der Besitzer damit vorhat.
```powershell
py zentrale_client.py --agent claude notiz-neu "MacBook-Air-2015" --ordner Geräte --text-datei macbook.md
```
Namen kurz und ohne Leerzeichen: `MacBook-Air-2015`, `Alter-PC`, `ThinkPad-T450`. Dieselben Namen nimmst du für den Melder.
**Ende:** Tabelle aller Geräte, Frage: „Zentrale fürs Heimnetz öffnen?“

## 2. Zentrale im Heimnetz erreichbar machen (nach Ja)

Bisher hört die Zentrale nur auf den eigenen Rechner. Damit andere Geräte melden können:

1. Mit `--heimnetz` starten: `py start.py --heimnetz` (im Autostart `docs/AUTOSTART.md` das Argument `"start.py" --heimnetz`
   eintragen, oder die Umgebungsvariable `ZENTRALE_HEIMNETZ=1`). Die Zentrale nimmt dann Anfragen aus dem Heimnetz
   (private Adressen, wie sie jeder Router vergibt) und von Tailscale an und weist alles andere ab. Ohne Schlüssel gibt es
   weiter keine Daten.
2. **Windows-Firewall**, nur für das Profil „Privat“ und nur das eigene Netz und Tailscale:
   ```powershell
   Get-NetConnectionProfile          # Das Heimnetz muss „Private“ sein. Sonst nach Ja: Set-NetConnectionProfile -InterfaceAlias "<Name>" -NetworkCategory Private
   New-NetFirewallRule -DisplayName "Zentrale (Heimnetz)" -Direction Inbound -Protocol TCP -LocalPort 8090 -Profile Private `
       -RemoteAddress LocalSubnet,100.64.0.0/10 -Action Allow     # 100.64.0.0/10 = Tailscale
   ```
   Rückgängig: `Remove-NetFirewallRule -DisplayName "Zentrale (Heimnetz)"`. Danach dem Besitzer sagen, was du geöffnet
   hast, warum und wie es rückgängig geht.
   Mac: Die Firewall fragt beim ersten Start, „Erlauben“. Linux mit ufw: `sudo ufw allow from <eigenes Netz>/24 to any port 8090 proto tcp` (das eigene Netz zeigt `ip -4 route`)
   und `sudo ufw allow in on tailscale0 to any port 8090 proto tcp`.
3. Soll die Seite statt der IP einen Namen zeigen (z. B. `http://heimserver:8090`): `ZENTRALE_HOSTS=heimserver` und
   `ZENTRALE_ADRESSEN=http://heimserver:8090` setzen. Der Rechnername selbst ist schon erlaubt.
4. Prüfen: auf einem anderen Gerät im Browser `http://<IP>:8090` öffnen, der Besitzer gibt seinen Schlüssel ein.
   Homelab → Netzwerk zeigt unter „Zentrale erreichen“ die Adresse.

## 3. Melder auf jedem Gerät (nach Ja)

Je Gerät (auch auf dem Rechner, auf dem die Zentrale läuft):

1. Schlüssel anlegen, auf dem Rechner mit der Zentrale: `py start.py geraet-neu "MacBook-Air-2015"`. Er landet als Datei
   `geraet-macbook-air-2015.key` im Schlüssel-Ordner und darf **nur melden**, sonst nichts. Der Befehl zeigt die fertigen
   Befehle für das Gerät.
2. Die Schlüsseldatei aufs Gerät bringen: USB-Stick oder Netzwerkordner, **nie per Chat oder Mail**.
3. Auf dem Gerät (Terminal bzw. PowerShell):
   ```
   curl -o melder.py http://<IP der Zentrale>:8090/melder.py
   python3 melder.py --zeigen                                     # zeigt, was gemeldet würde, schickt nichts
   python3 melder.py einrichten --zentrale http://<IP>:8090 --name "MacBook-Air-2015" --schluessel-datei geraet-macbook-air-2015.key
   python3 melder.py autostart                                    # zeigt die Autostart-Befehle für dieses System
   ```
   Unter Windows `py` statt `python3`; den Download macht dort der Befehl aus Schritt 1. Den Melder in einen festen Ordner
   legen (z. B. `C:\Zentrale-Melder\` oder `~/zentrale-melder/`), nicht in Downloads. Danach die Schlüsseldatei in den
   Papierkorb des Geräts.
4. Autostart: die von `autostart` gezeigten Befehle ausführen (Windows Aufgabenplanung „Zentrale Melder“, Mac launchd,
   Linux systemd). Nach einer Minute steht das Gerät unter Homelab → Geräte.

**Alte Macs:** Der Melder braucht Python 3.6 oder neuer. `python3 --version` im Terminal. Fehlt es, bietet macOS die
„Command Line Tools“ an (Python 3.8 oder 3.9, reicht), oder der Installer von python.org (für macOS 10.9 und neuer). Ist
das Gerät älter als macOS 10.9, gibt es kein passendes Python mehr: dann Linux darauf (Schritt 4) oder ohne Melder lassen
und nur als Notiz führen. Temperatur zeigt macOS ohne Administrator nicht, das ist normal.

**Was der Melder schickt:** Name, System, Modell, Laufzeit, Prozessor, Arbeitsspeicher, Laufwerke mit freiem Platz und
Papierkorb-Größe, Akku (Ladung, Zyklen, Zustand), Temperatur (wo ohne Administrator lesbar), IP im Heimnetz, Tailscale,
bei Linux Updates, Neustart nötig, Systemdienste und Docker. Keine Dateinamen, keine Inhalte, keine Passwörter.

## 4. Welches Gerät wird der Server? (Vorschlag, kein Umbau)

Schau die Notizen aus Schritt 1 an und schlag **ein** Gerät vor, mit Begründung als Tabelle:

| Was zählt | Warum |
|---|---|
| leise und sparsam im Dauerbetrieb | läuft Tag und Nacht. Ein Laptop braucht oft 5–10 W, ein alter Tower 40–80 W. |
| Akku noch brauchbar | ein Laptop-Akku überbrückt Stromausfälle wie eine kleine USV |
| Platte | SSD für das System. Für Ablage und Sicherung eine zweite Platte (intern oder USB) |
| Arbeitsspeicher | 4 GB reichen, 8 GB sind bequem |
| Linux-tauglich | 64-Bit, Netzwerkkarte am Kabel. WLAN geht, Kabel ist besser. |
| wird nicht mehr gebraucht | der Besitzer arbeitet nicht mehr daran |

Empfehlung: Debian (stabil, sparsam, lange Updates) ohne Desktop. Frag: „Soll <Gerät> der Server werden?“

## 5. Server aufsetzen und Zentrale umziehen (nach Ja)

1. **Erst sichern:** alles, was auf dem Gerät noch wichtig ist, mit dem Besitzer auf ein anderes Gerät oder einen Stick
   kopieren und mit Prüfsummen vergleichen (`aufraeumen\sichern.py`, wie in Phase 1 von AGENTS.md). Ohne geprüfte Sicherung geht es
   nicht weiter.
2. **Linux installieren macht der Besitzer selbst.** Du gibst ihm eine kurze Anleitung für genau dieses Gerät: Stick mit
   Debian-Installer erstellen (Rufus unter Windows, balenaEtcher am Mac, beide Open Source), vom Stick starten,
   „Gesamte Platte verwenden“ (das löscht das Gerät, deshalb erst sichern), nur „SSH-Server“ und „Standard-Systemwerkzeuge“
   wählen, einen Benutzer anlegen. Das Passwort tippt nur er.
3. Danach per SSH weiter (mit Schlüssel, nicht mit Passwort, sobald es geht): `sudo apt update && sudo apt full-upgrade`,
   `sudo apt install python3 git`, automatische Sicherheits-Updates (`unattended-upgrades`). Laptop: Deckel zu darf nicht
   in den Ruhezustand gehen (`HandleLidSwitch=ignore` in `/etc/systemd/logind.conf`).
4. **Zentrale umziehen**, ohne Vermischung (wie `docs/EINRICHTEN.md`):
   - Auf dem Server das Repo klonen (`git clone … ~/zentrale-starter`), dann die Zentrale auf dem alten Rechner beenden.
   - Den Ordner `daten` als **Kopie** auf den Server bringen (scp oder USB) und mit Prüfsummen vergleichen
     (`sha256sum` bzw. `Get-FileHash`). Nichts verschieben, das Original bleibt bis zum Schluss liegen.
   - Auf dem Server starten: `python3 start.py --heimnetz`, als Dienst (systemd, Muster in `docs/AUTOSTART.md` unter Linux).
   - Den Autostart der Zentrale auf dem alten Rechner **abschalten, nicht löschen** (`Disable-ScheduledTask -TaskName Zentrale`).
     Der alte Ordner bleibt angehalten liegen.
   - Auf allen Geräten, auf denen Agenten arbeiten: `ZENTRALE_URL=http://<Server>:8090` setzen (Windows:
     `[Environment]::SetEnvironmentVariable("ZENTRALE_URL", "http://<Server>:8090", "User")`) und die Agenten-Schlüssel
     dorthin kopieren. Dann `py einrichten.py pruefen`: muss „Alles getrennt“ zeigen.
   - Melder: auf jedem Gerät `melder.py einrichten` mit der neuen Adresse noch einmal.
   - Der Besitzer setzt im Browser ein Lesezeichen auf die neue Adresse.

## 6. Tailscale (der Besitzer meldet sich an)

Tailscale verbindet die Geräte, auch von unterwegs, ohne etwas ins Internet zu öffnen. Installieren darfst du (nach
Ja, Größe nennen, rund 30–100 MB). **Anmelden macht der Besitzer selbst**: `tailscale up` (Linux), sonst die App.
Danach ist die Zentrale von überall unter `http://<Tailscale-IP des Servers>:8090` erreichbar (die Zentrale lässt
Tailscale-Adressen zu). Mit MagicDNS geht auch der Name: dann `ZENTRALE_HOSTS=<name>` setzen.
Nie Funnel oder Portweiterleitung im Router für die Zentrale.

## 7. Freigabe „Ablage“ und nächtliche Sicherung (nach Ja)

- **Ablage:** auf dem Server ein Ordner `/srv/ablage` auf der Datenplatte, im Heimnetz und über Tailscale als
  Samba-Freigabe (`sudo apt install samba`, eine Freigabe `[Ablage]`, nur für den Benutzer des Besitzers). Das
  Samba-Passwort setzt der Besitzer selbst (`sudo smbpasswd -a <benutzer>`). Firewall nur fürs Heimnetz und Tailscale.
  Dort hinein, was mehrere Geräte brauchen; große Dateien gehören nicht auf die Laptops.
- **Sicherung:** restic (`sudo apt install restic`), Ziel eine zweite Platte (z. B. `/mnt/sicherung`), jede Nacht um 3 Uhr
  per systemd-Timer: die Daten der Zentrale und die Ablage. Aufbewahren: 7 Tage, 4 Wochen, 6 Monate (`restic forget
  --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --prune`). Das restic-Passwort wählt der Besitzer und legt es in seinen
  Passwort-Manager; ohne Passwort ist die Sicherung verloren. Einmal im Monat eine Stichprobe zurückholen und vergleichen.
- Der Melder des Servers meldet ausgefallene Dienste: Fällt die Sicherung aus, steht es unter Homelab → Dienste.

## 8. Putzen auf jedem Gerät (nach Ja)

Auf jedem Gerät `aufraeumen/putzen.py` wie in `docs/PUTZEN.md`: erst `--probe`, als Tabelle zeigen, nach Ja `--los`, dann
die tägliche Putzrunde. Die Platten-Warnungen unter Homelab zeigen, wo es eng wird.

## Rückgängig

| Was | Wie |
|---|---|
| Heimnetz zu | ohne `--heimnetz` starten, `Remove-NetFirewallRule -DisplayName "Zentrale (Heimnetz)"` |
| Melder auf einem Gerät aus | Windows `Unregister-ScheduledTask -TaskName "Zentrale Melder"`, Mac `launchctl unload -w ~/Library/LaunchAgents/de.zentrale-starter.melder.plist`, Linux `sudo systemctl disable --now zentrale-melder` |
| Gerät aus der Liste | Homelab → Geräte → Gerät → „Vergessen“ (nur offline), Schlüssel ungültig: `py start.py agent-weg geraet-<name>` |
| Zentrale zurück auf den alten Rechner | Server-Zentrale beenden, auf dem alten `Enable-ScheduledTask -TaskName Zentrale`, `ZENTRALE_URL` entfernen. Was seit dem Umzug neu ist, liegt nur in `daten` auf dem Server. |
| Tailscale | App abmelden oder `tailscale down` |
