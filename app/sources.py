"""Datenquellen: Nginx Proxy Manager, Technitium, Proxmox, Docker."""
import ipaddress
import logging

import docker
import requests
import urllib3

log = logging.getLogger(__name__)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
TIMEOUT = 10
SKIP_ZONE_TYPES = {"Stub", "Catalog", "SecondaryCatalog"}


def is_ip(value):
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def npm_session(url, user, password):
    session = requests.Session()
    r = session.post(f"{url}/api/tokens", json={"identity": user, "secret": password}, timeout=TIMEOUT)
    r.raise_for_status()
    session.headers["Authorization"] = f"Bearer {r.json()['token']}"
    return session


def npm_raw_hosts(session, url):
    r = session.get(f"{url}/api/nginx/proxy-hosts", timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def npm_delete_host(session, url, host_id):
    r = session.delete(f"{url}/api/nginx/proxy-hosts/{host_id}", timeout=TIMEOUT)
    r.raise_for_status()


def npm_certificates(session, url):
    r = session.get(f"{url}/api/nginx/certificates", timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def npm_create_host(session, url, domain, forward_host, forward_port, scheme, certificate_id):
    """Proxy-Host mit den Einstellungen anlegen, die bei den bestehenden Hosts üblich sind."""
    payload = {
        "domain_names": [domain],
        "forward_scheme": scheme,
        "forward_host": forward_host,
        "forward_port": int(forward_port),
        "access_list_id": 0,
        "certificate_id": certificate_id or 0,
        "ssl_forced": bool(certificate_id),
        "http2_support": bool(certificate_id),
        "hsts_enabled": False,
        "hsts_subdomains": False,
        "caching_enabled": False,
        "block_exploits": True,
        "allow_websocket_upgrade": True,
        "advanced_config": "",
        "locations": [],
        "meta": {"letsencrypt_agree": False, "dns_challenge": False},
    }
    r = session.post(f"{url}/api/nginx/proxy-hosts", json=payload, timeout=TIMEOUT)
    if not r.ok:
        raise RuntimeError(f"NPM {r.status_code}: {r.text[:150]}")
    return r.json()


def npm_proxy_hosts(url, user, password):
    return [
        {
            "id": h["id"],
            "domains": [d.lower() for d in h["domain_names"]],
            "forward_host": str(h.get("forward_host", "")).lower(),
            "forward_port": h.get("forward_port"),
            "https": bool(h.get("certificate_id")),
        }
        for h in npm_raw_hosts(npm_session(url, user, password), url)
        if h.get("enabled", 1) and h.get("domain_names")
    ]


def _technitium(url, token, path, **params):
    r = requests.get(f"{url}/api/{path}", params={"token": token, **params}, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "ok":
        raise RuntimeError(data.get("errorMessage") or data.get("status"))
    return data.get("response")


def technitium_delete(url, token, record):
    params = {"domain": record["name"], "zone": record["zone"], "type": record["type"]}
    params["cname" if record["type"] == "CNAME" else "ipAddress"] = record["value"]
    _technitium(url, token, "zones/records/delete", **params)


def technitium_add(url, token, record):
    params = {"domain": record["name"], "zone": record["zone"], "type": record["type"], "ttl": 3600}
    params["cname" if record["type"] == "CNAME" else "ipAddress"] = record["value"]
    _technitium(url, token, "zones/records/add", **params)


def technitium_records(url, token, zones):
    """Liefert (Zonen, Einträge) – A/AAAA/CNAME ohne Zonen-Apex; Wildcards mit wildcard=True."""

    def api(path, **params):
        return _technitium(url, token, path, **params)

    if not zones:
        zones = [
            z["name"].lower()
            for z in api("zones/list")["zones"]
            if not z.get("internal") and not z.get("disabled")
            and z.get("type") not in SKIP_ZONE_TYPES and not z["name"].endswith(".arpa")
        ]
    records = []
    for zone in zones:
        for rec in api("zones/records/get", domain=zone, zone=zone, listZone="true")["records"]:
            name = rec["name"].lower()
            if rec.get("disabled") or rec["type"] not in ("A", "AAAA", "CNAME"):
                continue
            if name == zone:
                continue
            rdata = rec.get("rData") or {}
            value = str(rdata.get("ipAddress") or rdata.get("cname") or "").lower()
            records.append({"name": name, "type": rec["type"], "value": value, "zone": zone,
                            "wildcard": name.startswith("*.")})
    return zones, records


def proxmox_guests(url, token_id, secret):
    session = requests.Session()
    session.verify = False
    session.headers["Authorization"] = f"PVEAPIToken={token_id}={secret}"

    def get(path, **params):
        r = session.get(f"{url}/api2/json{path}", params=params, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()["data"]

    guests = []
    for g in get("/cluster/resources", type="vm"):
        if g.get("template"):
            continue
        guest = {
            "vmid": int(g["vmid"]),
            "name": (g.get("name") or f"vm{g['vmid']}").lower(),
            "node": g["node"],
            "type": g["type"],
            "running": g.get("status") == "running",
            "ips": [],
        }
        if guest["running"]:
            guest["ips"] = _guest_ips(get, guest)
        guests.append(guest)
    if not guests and not get("/access/permissions"):
        raise RuntimeError("Token hat keine Rechte (PVEAuditor auf / für User und Token setzen)")
    return guests


def _guest_ips(get, guest):
    try:
        if guest["type"] == "lxc":
            data = get(f"/nodes/{guest['node']}/lxc/{guest['vmid']}/interfaces") or []
            ips = [i.get("inet", "").split("/")[0] for i in data]
        else:
            data = get(f"/nodes/{guest['node']}/qemu/{guest['vmid']}/agent/network-get-interfaces") or {}
            ips = [a.get("ip-address", "") for i in data.get("result", []) for a in i.get("ip-addresses", [])]
    except requests.RequestException:
        return []  # z. B. kein Gast-Agent in der VM
    return [ip for ip in ips if is_ip(ip) and not ipaddress.ip_address(ip).is_loopback
            and not ipaddress.ip_address(ip).is_link_local]


def docker_containers(servers, local_host):
    """Laufende Container aller Server aus Homepages docker.yaml → (Container, erreichbare Server, Fehler)."""
    containers, reachable, errors = [], set(), []
    for name, cfg in (servers or {}).items():
        if not isinstance(cfg, dict):
            continue
        if cfg.get("socket"):
            base, host = f"unix://{cfg['socket']}", local_host
        elif cfg.get("host"):
            base, host = f"tcp://{cfg['host']}:{cfg.get('port', 2375)}", cfg["host"]
        else:
            continue
        try:
            raw = docker.DockerClient(base_url=base, timeout=8).api.containers()
        except Exception as exc:  # docker wirft je nach Fehler sehr unterschiedliche Typen
            errors.append(f"Docker-Server `{name}` nicht erreichbar ({_short(exc)})")
            continue
        reachable.add(name)
        for c in raw:
            networks = (c.get("NetworkSettings") or {}).get("Networks") or {}
            containers.append({
                "server": name,
                "host": host,
                "local": bool(cfg.get("socket")),
                "name": c["Names"][0].lstrip("/").lower(),
                "image": c.get("Image", ""),
                "labels": c.get("Labels") or {},
                "ports": sorted({p["PublicPort"] for p in c.get("Ports", []) if p.get("PublicPort")}),
                "private_ports": sorted({p["PrivatePort"] for p in c.get("Ports", []) if p.get("PrivatePort")
                                         and p.get("Type", "tcp") == "tcp"}),
                "port_map": {p["PrivatePort"]: p["PublicPort"] for p in c.get("Ports", []) if p.get("PublicPort")},
                "ips": [n["IPAddress"] for n in networks.values() if n.get("IPAddress")],
                "networks": sorted(networks),
            })
    return containers, reachable, errors


def probe_http(host):
    """Antwortet unter dem Namen ein Webserver? → URL oder None."""
    for scheme in ("https", "http"):
        try:
            requests.get(f"{scheme}://{host}", timeout=3, verify=False, allow_redirects=False)
            return f"{scheme}://{host}"
        except requests.RequestException:
            continue
    return None


_icon_cache = {}


def icon_exists(name):
    if name not in _icon_cache:
        try:
            r = requests.head(f"https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/png/{name}.png", timeout=5)
            _icon_cache[name] = r.status_code == 200
        except requests.RequestException:
            _icon_cache[name] = False
    return _icon_cache[name]


def _short(exc):
    text = str(exc)
    if any(s in text for s in ("Connection refused", "ECONNREFUSED", "Failed to establish", "Max retries")):
        return "Verbindung abgelehnt"
    if "timed out" in text.lower():
        return "Zeitüberschreitung"
    return text[:120]
