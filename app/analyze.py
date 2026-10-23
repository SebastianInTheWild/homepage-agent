"""Abgleich: Was läuft im Homelab, was steht in Homepage?"""
import fnmatch
import logging
import re
import socket
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from . import homepage, provision, sources
from .homepage import host_of, slug
from .portainer import Portainer

log = logging.getLogger(__name__)

# Container, die ohne Proxy-Host nie ins Dashboard gehören
INFRA_IMAGES = ("postgres", "mariadb", "mysql", "redis", "valkey", "mongo", "watchtower", "cloudflared",
                "cloudflare-ddns", "socket-proxy")
NON_WEB_PORTS = {22, 53, 502, 1883, 4712, 5683, 8883}


@dataclass
class Candidate:
    id: str
    name: str
    href: str = ""
    hosts: list = field(default_factory=list)
    slugs: list = field(default_factory=list)
    containers: list = field(default_factory=list)
    vmids: list = field(default_factory=list)
    ips: list = field(default_factory=list)
    sources: list = field(default_factory=list)
    server: str = ""
    container: str = ""
    image: str = ""
    description: str = ""
    proxmox: dict = field(default_factory=dict)
    icon: str = ""
    group: str = ""
    origin: str = ""  # npm | dns | docker | proxmox – woraus der Vorschlag entstand
    compose: dict = field(default_factory=dict)  # Stack/Service, falls lokaler Compose-Container
    target: dict = field(default_factory=dict)  # gesetzt, wenn als Docker-Label eintragbar

    def add_slugs(self, *values):
        for value in values:
            s = slug(value)
            if s and s not in self.slugs:
                self.slugs.append(s)


@dataclass
class Report:
    missing: list
    stale: list
    lint: list
    labels: list
    provisions: list
    errors: list
    total: int
    groups: list


def pretty(text):
    return " ".join(w[:1].upper() + w[1:] for w in re.split(r"[-_.\s]+", text) if w)


def _attach_container(c, cont):
    if c.container:
        return
    c.container, c.server, c.image = cont["name"], cont["server"], cont["image"]
    c.containers.append(cont["name"])
    project = cont["labels"].get("com.docker.compose.project", "")
    c.add_slugs(cont["name"], project)
    if cont.get("local") and project and cont["labels"].get("com.docker.compose.service"):
        c.compose = {"project": project, "service": cont["labels"]["com.docker.compose.service"]}
    desc = cont["labels"].get("org.opencontainers.image.description", "")
    if desc and len(desc) <= 60 and not c.description:
        c.description = desc
    c.sources.append(f"Container `{cont['name']}` auf `{cont['server']}`")


def _attach_guest(c, guest):
    if c.proxmox:
        return
    c.proxmox = {"proxmoxNode": guest["node"], "proxmoxVMID": guest["vmid"], "proxmoxType": guest["type"]}
    c.vmids.append(guest["vmid"])
    c.ips += [ip for ip in guest["ips"] if ip not in c.ips]
    c.add_slugs(guest["name"])
    kind = "LXC" if guest["type"] == "lxc" else "VM"
    c.sources.append(f"{kind} {guest['vmid']} `{guest['name']}` auf Node `{guest['node']}`")


def build_candidates(npm, records, guests, containers, settings):
    records = [r for r in records if not r["wildcard"]]
    dns_ip = {r["name"]: r["value"] for r in records if r["type"] in ("A", "AAAA")}

    def resolve(host):
        if not host or sources.is_ip(host):
            return host
        if host in dns_ip:
            return dns_ip[host]
        try:
            return socket.gethostbyname(host)
        except OSError:
            return ""

    for cont in containers:
        cont["host_ip"] = resolve(cont["host"])
    cont_by_name = {c["name"]: c for c in containers}
    cont_by_ip = {ip: c for c in containers for ip in c["ips"]}
    cont_by_port = {(c["host_ip"], p): c for c in containers for p in c["ports"]}
    guest_by_ip = {ip: g for g in guests for ip in g["ips"]}
    guest_by_slug = {slug(g["name"]): g for g in guests}
    targets = Counter(resolve(h["forward_host"]) or h["forward_host"] for h in npm)
    used_containers, used_guests, items = set(), set(), []

    def find(slugs=(), ips=()):
        return next((c for c in items if set(slugs) & set(c.slugs) or set(ips) & set(c.ips)), None)

    # 1. Proxy-Hosts – die verlässlichste Liste echter Dienste
    for h in npm:
        dom = h["domains"][0]
        c = Candidate(id=f"proxy:{dom}", name=pretty(dom.split(".")[0]), origin="npm",
                      href=f"{'https' if h['https'] else 'http'}://{dom}", hosts=list(h["domains"]))
        c.add_slugs(*(d.split(".")[0] for d in h["domains"]))
        c.sources.append(f"Proxy-Host `{dom}` → `{h['forward_host']}:{h['forward_port']}`")
        fwd = h["forward_host"]
        ip = resolve(fwd)
        cont = cont_by_name.get(fwd) or cont_by_ip.get(fwd) or cont_by_port.get((ip, h["forward_port"]))
        if cont:
            _attach_container(c, cont)
            used_containers.add((cont["server"], cont["name"]))
        if targets[ip or fwd] == 1:  # nur eindeutige Ziele, sonst wäre z. B. der Docker-Host jeder Dienst
            guest = guest_by_ip.get(ip) or (None if sources.is_ip(fwd) else guest_by_slug.get(slug(fwd.split(".")[0])))
            if guest:
                _attach_guest(c, guest)
                used_guests.add(guest["vmid"])
        items.append(c)

    # 1b. DNS-Namen, die auf den Proxy zeigen (CNAME/A) – Dienste, auch wenn NPM nichts liefert
    npm_ip = resolve(host_of(settings.npm_url))
    cont_by_slug = {}
    for cont in containers:
        for key in (cont["name"], cont["labels"].get("com.docker.compose.project", "")):
            cont_by_slug.setdefault(slug(key), cont)
    covered = {h for c in items for h in c.hosts}
    cname_targets = {r["value"] for r in records if r["type"] == "CNAME"}
    for r in records:
        target = dns_ip.get(r["value"]) if r["type"] == "CNAME" else r["value"]
        if not npm_ip or target != npm_ip or r["name"] in covered or r["name"] in cname_targets:
            continue  # der Name des Proxy-Hosts selbst ist kein Dienst
        label = r["name"].split(".")[0]
        c = Candidate(id=f"proxy:{r['name']}", name=pretty(label), href=f"https://{r['name']}", hosts=[r["name"]],
                      origin="dns")
        c.add_slugs(label)
        c.sources.append(f"DNS `{r['name']}` → Proxy (`{r['value']}`)")
        cont = cont_by_slug.get(slug(label))
        if cont and (cont["server"], cont["name"]) not in used_containers:
            _attach_container(c, cont)
            used_containers.add((cont["server"], cont["name"]))
        items.append(c)

    # 2. Container mit veröffentlichten Ports, die kein Proxy-Host abdeckt
    for cont in containers:
        if (cont["server"], cont["name"]) in used_containers or not cont["ports"]:
            continue
        image = cont["image"].split("/")[-1].split(":")[0]
        if any(i in image for i in INFRA_IMAGES):
            continue
        existing = find([slug(cont["name"])])
        if existing:
            _attach_container(existing, cont)
            continue
        port = next((p for p in cont["ports"] if p not in NON_WEB_PORTS), cont["ports"][0])
        c = Candidate(id=f"docker:{cont['server']}/{cont['name']}", name=pretty(cont["name"]), origin="docker",
                      href=f"http://{cont['host']}:{port}" if cont["host"] else "")
        _attach_container(c, cont)
        c.sources[-1] += f" (Ports {', '.join(map(str, cont['ports']))})"
        items.append(c)

    # 3. Laufende VMs/LXCs
    for guest in guests:
        if guest["vmid"] in used_guests or not guest["running"]:
            continue
        existing = find([slug(guest["name"])], guest["ips"])
        if existing:
            _attach_guest(existing, guest)
            continue
        c = Candidate(id=f"pve:{guest['vmid']}", name=pretty(guest["name"]), origin="proxmox")
        c.hosts = [n for n, ip in dns_ip.items() if ip in guest["ips"]]
        _attach_guest(c, guest)
        items.append(c)

    # 4. DNS-Namen mit Webserver, die sonst nirgends auftauchen
    covered = {h for c in items for h in c.hosts}
    dns_only = []
    for r in records:
        if r["type"] == "CNAME" or r["name"] in covered or r["value"] == npm_ip:
            continue
        label = r["name"].split(".")[0]
        existing = find([slug(label)], [r["value"]])
        if existing:
            existing.hosts.append(r["name"])
            continue
        c = Candidate(id=f"dns:{r['name']}", name=pretty(label), hosts=[r["name"]], ips=[r["value"]], origin="dns")
        c.add_slugs(label)
        c.sources.append(f"DNS-Eintrag `{r['name']}` → `{r['value']}`")
        dns_only.append(c)

    # URLs ergänzen bzw. DNS-Kandidaten ohne Webserver verwerfen
    to_probe = [c for c in items if not c.href and c.hosts] + (dns_only if settings.probe_dns else [])
    with ThreadPoolExecutor(max_workers=20) as pool:
        urls = list(pool.map(lambda c: next(filter(None, map(sources.probe_http, c.hosts)), None), to_probe))
    for c, url in zip(to_probe, urls):
        c.href = url or ""
    items += [c for c in dns_only if c.href]
    return items


def known_index(entries, containers):
    known = {"hosts": set(), "slugs": set(), "containers": set(), "vmids": set()}
    for e in entries:
        cfg = e["cfg"]
        known["slugs"].add(slug(e["name"]))
        widget = cfg.get("widget") if isinstance(cfg.get("widget"), dict) else {}
        for url in (cfg.get("href"), cfg.get("siteMonitor"), widget.get("url")):
            if host_of(url):
                known["hosts"].add(host_of(url))
        if cfg.get("container"):
            known["containers"].add(str(cfg["container"]).lower())
        if str(cfg.get("proxmoxVMID", "")).isdigit():
            known["vmids"].add(int(cfg["proxmoxVMID"]))
    for cont in containers:  # Dienste, die sich per Docker-Label selbst eintragen
        labels = cont["labels"]
        if "homepage.name" in labels or "homepage.group" in labels:
            known["containers"].add(cont["name"])
            known["slugs"].add(slug(labels.get("homepage.name")))
            if host_of(labels.get("homepage.href")):
                known["hosts"].add(host_of(labels.get("homepage.href")))
    known["slugs"].discard("")
    return known


def is_known(c, known):
    return bool(set(c.hosts) & known["hosts"] or set(c.containers) & known["containers"]
                or set(c.vmids) & known["vmids"] or set(c.slugs) & known["slugs"])


def is_ignored(c, ignored_ids, patterns):
    if c.id in ignored_ids:
        return True
    names = [c.id, *c.hosts, *c.containers, *c.slugs]
    return any(fnmatch.fnmatch(n, p) for p in patterns for n in names)


def dns_has(host, records):
    names = {r["name"] for r in records}
    return host in names or ("." in host and "*." + host.split(".", 1)[1] in names)


def check_labels(containers, npm, zones, records, ok):
    """Container mit homepage.href-Label: Gibt es Proxy-Host und DNS-Eintrag für die Domain?"""
    issues = []
    npm_hosts = {d for h in npm for d in h["domains"]}
    for cont in containers:
        host = host_of(cont["labels"].get("homepage.href"))
        if not host or sources.is_ip(host) or not any(host == z or host.endswith("." + z) for z in zones):
            continue
        missing = []
        if ok.get("npm") and host not in npm_hosts:
            missing.append("Proxy-Host in NPM")
        if ok.get("dns") and not dns_has(host, records):
            missing.append("DNS-Eintrag")
        if missing:
            name = cont["labels"].get("homepage.name") or cont["name"]
            issues.append(f"*{name}* (Label an `{cont['name']}`): für `{host}` fehlt {' und '.join(missing)}")
    return issues


def find_stale(entries, npm, zones, records, guests, containers, reachable, ok):
    issues = []
    npm_hosts = {d for h in npm for d in h["domains"]}
    suffixes = set(zones) | {d.split(".", 1)[1] for d in npm_hosts if "." in d}
    running = {(c["server"], c["name"]) for c in containers}
    vmids = {g["vmid"] for g in guests}
    for e in entries:
        cfg, name = e["cfg"], e["name"]
        server, cont = cfg.get("server"), cfg.get("container")
        if cont and server in reachable and (server, str(cont).lower()) not in running:
            issues.append(f"*{name}*: Container `{cont}` läuft nicht auf `{server}`")
        vmid = str(cfg.get("proxmoxVMID", ""))
        if vmid.isdigit() and ok.get("proxmox") and int(vmid) not in vmids:
            issues.append(f"*{name}*: VM/LXC {vmid} gibt es in Proxmox nicht")
        host = host_of(cfg.get("href"))
        if (host and ok.get("npm") and ok.get("dns") and any(host.endswith("." + s) for s in suffixes)
                and host not in npm_hosts and not dns_has(host, records)):
            issues.append(f"*{name}*: `{host}` ist weder Proxy-Host noch DNS-Eintrag")
    return issues


def suggest_group(c, entries, containers, groups, default):
    votes = Counter()
    for e in entries:
        if c.server and e["cfg"].get("server") == c.server:
            votes[e["top"]] += 2
        if c.proxmox and e["cfg"].get("proxmoxVMID"):
            votes[e["top"]] += 1
    for cont in containers:
        if c.server and cont["server"] == c.server and cont["labels"].get("homepage.group"):
            votes[cont["labels"]["homepage.group"]] += 2
    if votes:
        return votes.most_common(1)[0][0]
    if default:
        return default
    return "Services" if "Services" in groups or not groups else groups[0]


def suggest_icon(c):
    raw = [c.container, c.image.split("/")[-1].split(":")[0], c.hosts[0].split(".")[0] if c.hosts else "", c.name]
    names = []
    for value in raw:
        n = re.sub(r"[^a-z0-9-]+", "-", (value or "").lower()).strip("-")
        if n and n not in names:
            names.append(n)
    return next((f"{n}.png" for n in names if sources.icon_exists(n)), "mdi-application-outline")


def run(settings, ignored_ids=()):
    errors, ok = [], {}

    def safe(key, label, fn, default):
        try:
            value = fn()
            ok[key] = True
            return value
        except Exception as exc:  # jede Quelle darf einzeln ausfallen
            log.warning("%s: %s", label, exc)
            errors.append(f"{label}: {str(exc)[:150]}")
            ok[key] = False
            return default

    services_doc = homepage.load_yaml(settings.config_dir / "services.yaml")
    if services_doc is None:
        raise RuntimeError(f"services.yaml nicht gefunden in {settings.config_dir}")
    docker_doc = homepage.load_yaml(settings.config_dir / "docker.yaml") or {}
    entries = list(homepage.iter_services(services_doc))

    npm = safe("npm", "Nginx Proxy Manager", lambda: sources.npm_proxy_hosts(
        settings.npm_url, settings.npm_user, settings.npm_password), []) if settings.npm_url else []
    zones, records = safe("dns", "Technitium", lambda: sources.technitium_records(
        settings.technitium_url, settings.technitium_token, settings.technitium_zones),
        ([], [])) if settings.technitium_url else ([], [])
    guests = safe("proxmox", "Proxmox", lambda: sources.proxmox_guests(
        settings.proxmox_url, settings.proxmox_token_id, settings.proxmox_token_secret),
        []) if settings.proxmox_url else []
    containers, reachable, docker_errors = sources.docker_containers(docker_doc, settings.docker_host_ip)
    errors += docker_errors

    candidates = build_candidates(npm, records, guests, containers, settings)
    known = known_index(entries, containers)
    label_groups = {c["labels"]["homepage.group"] for c in containers if c["labels"].get("homepage.group")}
    groups = homepage.group_names(services_doc) + sorted(label_groups - set(homepage.group_names(services_doc)))

    editable = {}
    if settings.portainer_url and settings.portainer_api_key:
        editable = safe("portainer", "Portainer", lambda: Portainer(
            settings.portainer_url, settings.portainer_api_key, settings.portainer_endpoint_id).editable_stacks(), {})

    missing = []
    for c in candidates:
        if c.origin not in settings.candidate_sources:
            continue  # nur aus der primären Quelle (Standard: NPM) vorschlagen
        if is_known(c, known) or is_ignored(c, set(ignored_ids), settings.ignore):
            continue
        c.group = suggest_group(c, entries, containers, groups, settings.default_group)
        c.icon = suggest_icon(c)
        if c.compose.get("project") in editable:
            c.target = {"stack": c.compose["project"], "stack_id": editable[c.compose["project"]],
                        "service": c.compose["service"]}
        missing.append(c)

    provisions = []
    if provision.requested(containers):
        certs = safe("npm_certs", "NPM-Zertifikate", lambda: sources.npm_certificates(
            sources.npm_session(settings.npm_url, settings.npm_user, settings.npm_password), settings.npm_url), [])
        a_records = {r["name"]: r["value"] for r in records if r["type"] == "A"}
        npm_host = host_of(settings.npm_url)
        npm_ip = npm_host if sources.is_ip(npm_host) else a_records.get(npm_host, "")
        if not npm_ip and npm_host:
            try:
                npm_ip = socket.gethostbyname(npm_host)
            except OSError:
                npm_ip = ""
        provisions = [p for p in provision.plan(containers, npm, zones, records, certs, editable, npm_ip,
                                                settings.default_group)
                      if p["id"] not in set(ignored_ids)]

    return Report(
        missing=missing,
        stale=find_stale(entries, npm, zones, records, guests, containers, reachable, ok),
        lint=homepage.lint(entries, set(docker_doc) if docker_doc else None),
        labels=check_labels(containers, npm, zones, records, ok),
        provisions=provisions,
        errors=errors,
        total=len(candidates),
        groups=groups,
    )
