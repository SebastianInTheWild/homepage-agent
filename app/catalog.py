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
    (["netalertx", "pialert", "pi-alert"], "NetAlertX", "Network scanner and presence detection", "netalertx.png"),
    (["watchyourlan"], "WatchYourLAN", "Lightweight network IP scanner", "watchyourlan.png"),
    (["unifi", "unifi-controller", "unifi-network-application"], "UniFi", "Manage UniFi networks and devices",
     "unifi.png"),
]
_INDEX = {slug(alias): (name, desc, icon) for aliases, name, desc, icon in APPS for alias in aliases}
_ALIASES = {name: {slug(a) for a in aliases} for aliases, name, _desc, _icon in APPS}


def is_technical_name(current, catalog_name):
    """„Pdf“, „Whats Up Docker“ … = aus Domain/Container abgeleitet → durch den sprechenden Namen ersetzen."""
    if current.lower() == catalog_name.lower():
        return False  # nur Groß-/Kleinschreibung – kein Vorschlag wert
    return slug(current) in _ALIASES.get(catalog_name, set()) | {slug(catalog_name)}


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
        # Stack-Name nur als letzter Versuch: mehrere Apps können sich einen Stack teilen
        search = [name, *keys[:2], subdomain] if hit else [*keys[:2], subdomain, project]
        desc = sources.awesome(image, search) or (sources.docker_hub(image) if image else "")
    desc = desc or fallback or _short(labels.get("org.opencontainers.image.description", ""))
    return name, desc, icon


# Kategorien = Gruppen in Homepage. Aliase: so heißen passende Gruppen evtl. schon (werden dann weiterbenutzt).
CATEGORIES = {
    "Media": ["media", "multimedia", "entertainment", "streaming", "medien"],
    "Smart Home": ["smarthome", "home automation", "hausautomation", "iot", "energy", "energie"],
    "Productivity": ["productivity", "office", "documents", "dokumente", "tools", "personal"],
    "Communication": ["communication", "kommunikation", "notifications", "mail"],
    "Development": ["development", "dev", "entwicklung", "code"],
    "Network": ["network", "netzwerk", "networking", "dns", "proxy"],
    "Monitoring": ["monitoring", "überwachung", "metrics", "status"],
    "Infrastructure": ["infrastructure", "homelab", "infra", "server", "system", "admin", "management"],
}
CATEGORY_OF = {
    "Plex": "Media", "Overseerr": "Media", "JDownloader": "Media", "FileBot": "Media", "Jellyfin": "Media",
    "Sonarr": "Media", "Radarr": "Media", "Prowlarr": "Media", "Huntarr": "Media", "Immich": "Media",
    "Twitch Drops Miner": "Media",
    "evcc": "Smart Home", "evcc Optimizer": "Smart Home", "Kia/Hyundai Token": "Smart Home",
    "Home Assistant": "Smart Home", "Home Assistant MCP": "Smart Home", "Mosquitto": "Smart Home",
    "SOLECTRUS": "Smart Home", "Node-RED": "Smart Home", "Zigbee2MQTT": "Smart Home", "NVR": "Smart Home",
    "Frigate": "Smart Home", "PhoneBlock": "Smart Home",
    "Stirling PDF": "Productivity", "Tandoor": "Productivity", "TimeTagger": "Productivity",
    "KitchenOwl": "Productivity", "Mealie": "Productivity", "Paperless-ngx": "Productivity",
    "Nextcloud": "Productivity", "Radicale": "Productivity", "Baïkal": "Productivity",
    "Contacts (CardDAV)": "Productivity", "Wichteln": "Productivity", "Vaultwarden": "Productivity",
    "ntfy": "Communication", "SMTP Relay": "Communication",
    "VS Code Server": "Development", "Gitea": "Development", "Firefox": "Development",
    "Nginx Proxy Manager": "Network", "Technitium DNS": "Network", "Cloudflare Tunnel": "Network",
    "AdGuard Home": "Network", "Pi-hole": "Network", "OpenSpeedTest": "Network", "NetAlertX": "Network",
    "WatchYourLAN": "Network", "UniFi": "Network",
    "Speedtest Tracker": "Monitoring", "What's up Docker": "Monitoring", "Uptime Kuma": "Monitoring",
    "Grafana": "Monitoring", "InfluxDB": "Monitoring", "Proxmox Monitoring": "Monitoring",
    "Proxmox": "Infrastructure", "Portainer": "Infrastructure", "Dockge": "Infrastructure",
    "Homepage": "Infrastructure", "ZimaOS": "Infrastructure", "iVentoy": "Infrastructure",
}
# Rubriken von awesome-selfhosted → Kategorie (Stichwort im Abschnittstitel)
SECTION_KEYWORDS = [
    ("media", "Media"), ("video", "Media"), ("audio", "Media"), ("music", "Media"), ("photo", "Media"),
    ("download", "Media"), ("automation", "Smart Home"), ("internet of things", "Smart Home"),
    ("communication", "Communication"), ("e-mail", "Communication"), ("notification", "Communication"),
    ("software development", "Development"), ("dns", "Network"), ("proxy", "Network"), ("vpn", "Network"),
    ("network", "Network"), ("monitoring", "Monitoring"), ("analytics", "Monitoring"),
    ("status", "Monitoring"), ("dashboard", "Infrastructure"), ("self-hosting", "Infrastructure"),
    ("container", "Infrastructure"), ("backup", "Infrastructure"), ("recipe", "Productivity"),
    ("document", "Productivity"), ("calendar", "Productivity"), ("task", "Productivity"),
    ("time tracking", "Productivity"), ("note", "Productivity"), ("file", "Productivity"),
    ("password", "Productivity"), ("office", "Productivity"), ("money", "Productivity"),
]


def category_for(name, image="", keys=(), sources=None):
    """Passende Kategorie für einen Dienst: Katalog, sonst Rubrik in awesome-selfhosted, sonst None."""
    if name in CATEGORY_OF:
        return CATEGORY_OF[name]
    section = sources.section(image, [name, *keys]) if sources else ""
    for keyword, category in SECTION_KEYWORDS:
        if keyword in section.lower():
            return category
    return None


def group_for(category, existing_groups):
    """Vorhandene Gruppe, die zur Kategorie passt (z. B. „SmartHome“ für Smart Home), sonst die Kategorie selbst."""
    wanted = {slug(category), *(slug(a) for a in CATEGORIES.get(category, []))}
    return next((g for g in existing_groups if slug(g) in wanted), category)


def _pretty(text):
    return " ".join(w[:1].upper() + w[1:] for w in re.split(r"[-_.\s]+", text or "") if w)


def _short(text, limit=60):
    text = " ".join(text.split()).rstrip(".")
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut + " …"
