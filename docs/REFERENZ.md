# Referenzbilder: so sieht die Zentrale aus

Für Agenten. **So muss die Zentrale aussehen**, wenn sie richtig läuft (Fassung 2026-11-07). Die Bilder sind mit
Beispieldaten gemacht. Sieht die Zentrale des Besitzers anders aus, fehlt links „Agenten“ oder „Papierkorb“, oder steht
unten links eine andere Fassung als in `zentrale\hub.py`, dann arbeitest du an einer **alten oder falschen Zentrale**. Dann nicht weiterbauen,
sondern `AGENTS.md`, Abschnitt „Nur eine Zentrale“, befolgen.

Die Oberfläche wird nicht nachgebaut und nicht umgestaltet. Sie kommt fertig aus diesem Repo (`zentrale\index.src.html`).
Größere Änderungen nur nach Entwurf als Bild und OK des Besitzers (`REGELN.md`, „Oberflächen“).

Die Bilder 01 bis 17 stammen aus einer früheren Fassung: Dort fehlen in der Leiste noch Kalender, E-Mail und Inventar, und unten links steht eine ältere Fassung. Das ist kein Fehler. Es gilt immer `FASSUNG` in `zentrale\hub.py`.

| Bild | Seite | Worauf achten |
|---|---|---|
| ![](bilder/01-uebersicht.png) | **Übersicht** | Oben „Guten Tag“ mit Datum und wie viel auf dich wartet. Links „Wartet auf dich“ (je Bericht die aktuelle Frage mit Vorschlägen zum Antippen) und „Heute“ (deine Aufgaben zum Abhaken, unten neu eintragen). Rechts die Agenten, die Kachel Homelab (Geräte online, freier Platz, was zu tun ist) und vier Zahlen. Unten links „Fassung …“, dieselbe wie `FASSUNG` in `zentrale/hub.py`. |
| ![](bilder/02-agenten.png) | **Agenten** | Eine Karte je Agent mit Arbeit, Wunsch-Nummer und Balken. Darunter „Fertig gemeldet“. |
| ![](bilder/03-wuensche.png) | **Wünsche** | Oben die Zahl, darunter „Neuer Wunsch …“. Je Gruppe ein Abschnitt (zuklappbar) mit Karten: Nr., Priorität als !!!/!!/!, Text oder „Als Nächstes“ mit Balken, die letzte Notiz grau. Unten das Erledigte. |
| ![](bilder/04-wunsch-blatt.png) | Wunsch geöffnet | Erledigt, Verwerfen, Titel ändern; Gruppe, Priorität, Schritte mit Balken und „Schritt hinzufügen“, Notizen, Notiz schreiben. |
| ![](bilder/05-berichte.png) | **Berichte** | Links die Liste („Wartet auf dich“ oben, Nummer, Agent · Projekt, offene Fragen), rechts der Verlauf: Karte mit Kurzfassung und „Ganzen Bericht lesen“, dann **eine Frage nach der anderen** mit Vorschlägen zum Antippen, „noch N Fragen danach“. |
| ![](bilder/13-handy-bericht.png) | Bericht am Handy | Öffnet als Blatt, gleiche Reihenfolge, unten das Antwortfeld. |
| ![](bilder/06-projekte.png) | **Projekte** | Aktive Projekte als Karten (Symbol, Gerät, „Als Nächstes“, Balken, offene Aufgaben, % erledigt). Darunter Aufgaben ohne Projekt, Ruht, Archiv und „Neues Projekt“. |
| ![](bilder/07-notizen.png) | **Notizen** | Drei Spalten: links „Alle Notizen“, „Zuletzt“ und die festen Ordner (Besitzer, Geräte, Projekte, Aufräumen, Anleitungen, Übergaben), in der Mitte die Liste mit Suche und Knopf für neue Notiz, rechts die Notiz mit „Bearbeiten“ und Papierkorb. Am Handy nur die Liste, die Notiz öffnet als Blatt. |
| ![](bilder/12-notizen-ordner.png) | Ordner gewählt | Die Liste zeigt nur diesen Ordner, links ist er markiert. |
| ![](bilder/08-papierkorb.png) | **Papierkorb** | Oben die Summe. Je Papierkorb (C:\Papierkorb, Notizen) ein Abschnitt mit „Alles leeren“, in jeder Zeile „Löschen“, unten der Windows-Papierkorb mit „Leeren“. Löschen kann nur der Besitzer. |
| ![](bilder/09-papierkorb-blatt.png) | Name angetippt | Herkunft und Größe, „Zurücklegen“ und „Endgültig löschen“. |
| ![](bilder/10-uebersicht-dunkel.png) | dunkel | Folgt der Einstellung von Windows. |
| ![](bilder/11-handy-agenten.png) | Handy | Leiste unten statt links, bei vielen Seiten zum Wischen. |
| ![](bilder/14-finanzen.png) | **Finanzen** | Privat/Firma, Auge (Beträge sind verdeckt, bis man es antippt), Überblick/Haushaltsbuch. Vier Zahlen, Bald kündbar, Offen zu zahlen, Berater, Ein- und Ausgaben, Verträge und Abos, Sparziele. |
| ![](bilder/15-geraete.png) | **Homelab → Geräte** | Oben die Warnungen als Pillen (rot dringend, orange bald, grau Hinweise). Je Gerät eine Karte mit grünem bzw. grauem Punkt (online/offline), Ringen für Prozessor, Arbeitsspeicher und Platte, unten Akku und Laufzeit. Offline-Geräte blass. |
| ![](bilder/16-geraet-blatt.png) | Gerät angetippt | Warnungen, Ringe (auch Temperatur und Akku), Laufwerke mit Balken und Papierkorb, Akku, System, Netzwerk, Dienste. „Vergessen“ nur bei offline. |
| ![](bilder/17-speicher.png) | **Homelab → Speicher** | Oben alle Laufwerke zusammen, je Gerät eine Farbe. Darunter je Gerät die Laufwerke mit belegt, Papierkorb (orange) und frei. Fast volle in Rot. |
| ![](bilder/18-kalender.png) | **Kalender** | Oben die Zahl und wohin neue Termine kommen, darunter „Neuer Termin …“. Je Tag ein Abschnitt, auch mit fälligen Aufgaben. Unten „Kalender verbinden“: Geht auch ohne Konto. |
| ![](bilder/19-email.png) | **E-Mail** | Suche und Filter oben. Rot „Vorsicht: sieht nach Betrug aus“, wenn etwas auffällt, dann „Wichtig“ und „Alles andere“, darunter die Postfächer und ob Agenten mitlesen dürfen (Standard: aus). |
| ![](bilder/20-email-blatt.png) | Mail angetippt | „Wichtig“ bzw. „Nicht wichtig“ und „Erledigt“, bei einer Warnung auch „Kein Betrug“ und die Gründe. Absender, Anhänge nur als Name, der Text. Senden und Löschen gibt es nicht. |
| ![](bilder/23-email-postfach.png) | Postfach angetippt | Wie weit zurück (7 Tage bis 1 Jahr) und, nach „Anzeigen“, welche Ordner mitgelesen werden. |
| ![](bilder/21-inventar.png) | **Inventar** | Vier Zahlen, Eingabe für Suche oder Satz, Kategorien, Karten je Teil. Orange Menge und „nachkaufen“: unter der Mindestmenge. |
| ![](bilder/22-inventar-blatt.png) | Teil angetippt | Plus und Minus, Kerndaten, Fotos, Verlauf aller Buchungen. |

Die Leiste hat oben Übersicht, Agenten, Berichte, Wünsche, unter „Persönlich“ Projekte, Kalender, E-Mail, Inventar, Finanzen, Notizen und unter
„Homelab“ Geräte, Dienste (nur wenn ein Linux-Gerät meldet), Netzwerk, Speicher, Papierkorb.
