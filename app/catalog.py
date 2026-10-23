"""Sprechende Namen und Icons für bekannte Homelab-Apps, dazu englische Kurzbeschreibungen als Rückfall.

Erkannt wird über Image-Name, Container-, Stack- oder Subdomain-Namen (Aliase). Beschreibung in dieser
Reihenfolge: awesome-selfhosted → Docker Hub → Katalog → Image-Metadaten (OCI-Labels).
"""
import re

from .homepage import slug

# (Aliase, Name, Beschreibung, Icon oder None = automatisch suchen)
APPS = [
    (["plex", "pms-docker"], "Plex", "Stream movies and TV shows", "plex.png"),
    (["overseerr", "plex-request", "jellyseerr"], "Overseerr", "Requests for movies and TV shows", "overseerr.png"),
    (["jdownloader", "jdownloader2", "jdownload"], "JDownloader", "Download manager", "jdownloader.png"),
    (["filebot"], "FileBot", "Rename and organize media files", "filebot.png"),
    (["stirling-pdf", "s-pdf", "pdf"], "Stirling PDF", "Edit, merge and convert PDFs",
     "stirling-pdf.png"),
    (["ntfy", "push"], "ntfy", "Push notifications", "ntfy.png"),
    (["recipes", "tandoor"], "Tandoor", "Recipes and meal planning", "tandoor-recipes.png"),
    (["timetagger"], "TimeTagger", "Time tracking", "timetagger.png"),
    (["code-server", "codeserver", "vscode"], "VS Code Server", "VS Code in the browser", "vscode.png"),
    (["homepage", "dashboard"], "Homepage", "This dashboard", "homepage.png"),
    (["portainer", "portainer-ee", "portainer-ce", "docker"], "Portainer", "Manage Docker containers",
     "portainer.png"),
    (["speedtest-tracker", "speedtest"], "Speedtest Tracker", "Track internet speed",
     "speedtest-tracker.png"),
    (["openspeedtest"], "OpenSpeedTest", "Measure LAN speed", "openspeedtest.png"),
    (["huntarr"], "Huntarr", "Hunt missing media in the *arr apps", "huntarr.png"),
    (["iventoy"], "iVentoy", "Boot ISOs over the network (PXE)", None),
    (["twitch-drops-miner", "twitchdrops"], "Twitch Drops Miner", "Collect Twitch drops automatically", "twitch.png"),
    (["kitchenowl", "kitchowl"], "KitchenOwl", "Grocery list and recipes", "kitchenowl.png"),
    (["evcc"], "evcc", "Charge the EV with solar surplus", "evcc.png"),
    (["evcc-optimizer", "optimizer"], "evcc Optimizer", "Charging plans for evcc", "evcc.png"),
    (["firefox"], "Firefox", "Browser in a container", "firefox.png"),
    (["whatsupdocker", "wud", "whats-up-docker"], "What's up Docker", "Keep track of container updates",
     "whats-up-docker.png"),
    (["nginx-proxy-manager", "proxymanager", "npm"], "Nginx Proxy Manager", "Reverse proxy and certificates",
     "nginx-proxy-manager.png"),
    (["radicale"], "Radicale", "Calendars and contacts (CalDAV/CardDAV)", "radicale.png"),
    (["baikal"], "Baïkal", "Calendars and contacts (CalDAV/CardDAV)", "baikal.png"),
    (["carddav"], "Contacts (CardDAV)", "Sync address books", "mdi-card-account-details-outline"),
    (["mosquitto", "eclipse-mosquitto", "mqtt"], "Mosquitto", "MQTT broker", "mosquitto.png"),
    (["phoneblock", "answerbot"], "PhoneBlock", "Answering bot against spam calls", "mdi-phone-cancel"),
    (["wichteln"], "Wichteln", "Family Secret Santa draw", "mdi-gift-outline"),
    (["ha-mcp"], "Home Assistant MCP", "AI access to Home Assistant", "home-assistant.png"),
    (["kia-token", "bluelink-token", "bluelink"], "Kia/Hyundai Token", "Kia/Hyundai login token for evcc",
     "mdi-key-outline"),
    (["zimaos", "zima"], "ZimaOS", "NAS and media server", "zimaos.png"),
    (["nvr"], "NVR", "Video surveillance", "mdi-cctv"),
    (["proxmox", "pve"], "Proxmox", "Virtualization (VMs and containers)", "proxmox.png"),
    (["proxmonitor"], "Proxmox Monitoring", "Monitoring for the Proxmox host", "proxmox.png"),
    (["technitium", "dns-server", "dns"], "Technitium DNS", "DNS server for the home network", "technitium.png"),
    (["home-assistant", "homeassistant", "haos"], "Home Assistant", "Smart home", "home-assistant.png"),
    (["smtp-relay", "mailrelay", "postfix"], "SMTP Relay", "Mail relay for home services",
     "mdi-email-fast-outline"),
    (["solectrus"], "SOLECTRUS", "Solar power analytics", "sh-solectrus.png"),
    (["influx", "influxdb"], "InfluxDB", "Time series database", "influxdb.png"),
    (["dockge"], "Dockge", "Manage compose stacks", "dockge.png"),
    (["cloudflared"], "Cloudflare Tunnel", "Remote access via Cloudflare", "cloudflare.png"),
    (["jellyfin"], "Jellyfin", "Stream movies and TV shows", "jellyfin.png"),
    (["sonarr"], "Sonarr", "Manage TV shows", "sonarr.png"),
    (["radarr"], "Radarr", "Manage movies", "radarr.png"),
    (["prowlarr"], "Prowlarr", "Indexers for the *arr apps", "prowlarr.png"),
    (["nextcloud"], "Nextcloud", "Files, calendars and contacts", "nextcloud.png"),
    (["paperless-ngx", "paperless"], "Paperless-ngx", "Scan and archive documents", "paperless-ngx.png"),
    (["immich", "immich-server"], "Immich", "Photo and video backup", "immich.png"),
    (["vaultwarden"], "Vaultwarden", "Password manager", "vaultwarden.png"),
    (["uptime-kuma", "uptime"], "Uptime Kuma", "Uptime monitoring", "uptime-kuma.png"),
    (["grafana"], "Grafana", "Metrics dashboards", "grafana.png"),
    (["adguardhome", "adguard"], "AdGuard Home", "Network-wide ad blocking", "adguard-home.png"),
    (["pihole", "pi-hole"], "Pi-hole", "Network-wide ad blocking", "pi-hole.png"),
    (["gitea", "forgejo"], "Gitea", "Git server", "gitea.png"),
    (["mealie"], "Mealie", "Recipes and meal planning", "mealie.png"),
    (["frigate"], "Frigate", "Video surveillance with object detection", "frigate.png"),
    (["node-red", "nodered"], "Node-RED", "Flow-based automations", "node-red.png"),
    (["zigbee2mqtt"], "Zigbee2MQTT", "Zigbee devices via MQTT", "zigbee2mqtt.png"),
]
_INDEX = {slug(alias): (name, desc, icon) for aliases, name, desc, icon in APPS for alias in aliases}


def _image_name(image):
    return (image or "").split("/")[-1].split(":")[0].split("@")[0]


def lookup(*keys):
    """Erster Treffer über die Schlüssel (Image, Container, Stack, Subdomain) → (Name, Beschreibung, Icon)."""
    for key in keys:
        hit = _INDEX.get(slug(key))
        if hit:
            return hit
    return None


def describe(image="", container="", project="", domain="", labels=None, sources=None):
    """Name, Beschreibung und Icon-Vorschlag (Icon None = automatisch suchen) für einen Dienst.

    `sources` ist ein descriptions.Descriptions-Objekt (awesome-selfhosted, Docker Hub) oder None.
    """
    labels = labels or {}
    subdomain = domain.split(".")[0] if domain else ""
    keys = [_image_name(image), container, project, subdomain]
    hit = lookup(*keys)
    title = labels.get("org.opencontainers.image.title", "")
    if hit:
        name, fallback, icon = hit
    else:
        name = title if title and len(title) <= 30 else _pretty(subdomain or container or _image_name(image))
        fallback, icon = "", None
    desc = ""
    if sources:
        desc = sources.awesome(image, [*keys, name]) or (sources.docker_hub(image) if image else "")
    desc = desc or fallback or _short(labels.get("org.opencontainers.image.description", ""))
    return name, desc, icon


def _pretty(text):
    return " ".join(w[:1].upper() + w[1:] for w in re.split(r"[-_.\s]+", text or "") if w)


def _short(text, limit=60):
    text = " ".join(text.split()).rstrip(".")
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut + " …"
