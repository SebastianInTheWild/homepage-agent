# Homepage-Agent

Prüft regelmäßig, ob alle Dienste aus dem Homelab im [Homepage](https://gethomepage.dev)-Dashboard stehen,
und fragt in Slack nach, ob fehlende Dienste eingetragen werden sollen.

**Primäre Quelle:** Nginx Proxy Manager – jeder Proxy-Host ist ein Dienst. Technitium (DNS), Docker (alle Server
aus Homepages `docker.yaml`) und Proxmox reichern die Vorschläge an und erkennen veraltete Einträge
(`CANDIDATE_SOURCES` erweitert die Quellen). **Ziel:** Docker-Labels am Container oder `services.yaml`.

## Ablauf

1. Nach Zeitplan (`CHECK_SCHEDULE`, Standard täglich 08:00) kommt eine Zusammenfassung in den Slack-Channel.
2. Jeder fehlende Dienst bekommt eine eigene Nachricht (= eigener Thread), mit Gruppe-Auswahl und Buttons:
   **Eintragen** · **Anpassen …** (Name, URL, Beschreibung, Icon) · **Ignorieren** · **Später**.
3. Vor jeder Änderung landet ein Backup der `services.yaml` in `data/backups/`.

Außerdem meldet der Agent veraltete Einträge (Container weg, VM weg, Domain weg) und Tippfehler in der Config.

## Befehle (im Container)

```bash
python -m app dry-run   # nur prüfen und ausgeben
python -m app check     # sofort prüfen und nach Slack schicken
python -m app reset     # eigene Slack-Nachrichten löschen, Status zurücksetzen (Sicherung bleibt), neu prüfen
```

## Einrichtung

- Slack-App aus `slack-app-manifest.yaml` anlegen (Socket Mode, keine öffentliche URL nötig), Icon `slack-icon.png`.
- Variablen siehe `.env.example`; in Portainer als Stack-Umgebungsvariablen eintragen.
- Proxmox: User + Token mit Rolle `PVEAuditor` auf `/` (beide!).
- NPM: Benutzer mit Sichtbarkeit „Alle Einträge“ und Proxy-Hosts „Nur ansehen“.

## Docker-Labels statt services.yaml

Mit `PORTAINER_URL` und `PORTAINER_API_KEY` setzt **Eintragen** die Homepage-Labels direkt am Container:
Der Agent ergänzt die Compose-Datei des Portainer-Stacks und rollt ihn neu aus (Container startet neu).
Das geht für lokale Container in Stacks, deren Compose-Datei in Portainer liegt (nicht aus Git, Name eindeutig).
Alle anderen Dienste landen weiter in der `services.yaml`.

Container mit `homepage.href`-Label werden geprüft: Gibt es für die Domain einen Proxy-Host in NPM und einen DNS-Eintrag?

## Löschen

**Löschen …** fragt NPM und Technitium frisch ab, zeigt den Proxy-Host und die DNS-Einträge zum Dienst
und löscht erst nach Bestätigung. Vorher wird alles als JSON in `data/deleted/` gesichert.
Dafür braucht der NPM-Benutzer „Manage“ bei Proxy-Hosts und der Technitium-Token „Modify“ auf die Zonen.

## Neuen Dienst per Label anlegen

Im Compose eines neuen Stacks:

```yaml
    labels:
      - homepage-agent.domain=foo.example.lan   # Pflicht
      - homepage-agent.port=8080                # Container-Port, nötig bei mehreren Ports
      - homepage-agent.scheme=https             # nur falls der Dienst selbst HTTPS spricht
      - homepage.group=Services                 # optional, sonst Vorschlag
```

Der Agent meldet den Dienst in Slack mit **Anlegen**. Danach legt er an, was fehlt:
DNS-Eintrag (wie die übrigen Proxy-Dienste, z. B. CNAME auf den Proxy-Host), NPM-Proxy-Host (Weiterleitung auf den
Container-Namen, wenn er im Netz von NPM hängt, sonst auf Host-IP und Port; passendes Wildcard-Zertifikat,
HTTPS erzwungen) und die Homepage-Labels. Jeder Schritt meldet sich im Thread des Dienstes.

## Namen und Beschreibungen

Sprechende Namen und Icons kommen aus einem Katalog bekannter Homelab-Apps (`app/catalog.py`).
Die englische Kurzbeschreibung stammt der Reihe nach aus der Liste
[awesome-selfhosted](https://github.com/awesome-selfhosted/awesome-selfhosted) (CC BY-SA 3.0, wöchentlich
zwischengespeichert in `data/cache/`), aus Docker Hub, aus dem Katalog oder aus den Image-Metadaten.

## Lebt der Dienst noch? Empfehlung je Proxy-Host

Für jeden Proxy-Host prüft der Agent das Ziel (Container läuft / gestoppt / gibt es nicht mehr, IP:Port,
VM/LXC in Proxmox) und den Aufruf über die Domain (502/504 = Ziel tot, keine DNS-Auflösung).
Daraus wird eine Empfehlung: 🟢 Eintragen · 🟡 Prüfen · 🔴 Löschen (Reste einer alten Konfiguration).
Auch Dienste, die schon in Homepage stehen, aber tot sind, werden als Rest gemeldet.

## Gruppen

Jeder Dienst bekommt eine passende Kategorie (Media, Smart Home, Productivity, Communication, Development,
Network, Monitoring, Infrastructure) – aus dem Katalog oder der Rubrik in awesome-selfhosted. Passt eine
vorhandene Gruppe (z. B. „SmartHome“, „Homelab“), wird sie benutzt, sonst entsteht die Gruppe beim Eintragen
neu. Vorhandene Einträge in unpassenden Gruppen meldet die Zusammenfassung mit Empfehlung.
