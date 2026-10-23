"""Neue Dienste per Container-Label anlegen: DNS-Eintrag, NPM-Proxy-Host und Homepage-Labels.

Am Container (Compose):
    homepage-agent.domain=foo.example.lan   Pflicht
    homepage-agent.port=8080                            Container-Port, nötig bei mehreren Ports
    homepage-agent.scheme=https                         falls der Dienst selbst HTTPS spricht
Vorhandene homepage.*-Labels (group, name, icon, description) werden übernommen.
"""
import re
from collections import Counter

from . import catalog, homepage, sources
from .homepage import host_of
from .portainer import Portainer

LABEL = "homepage-agent.domain"
NPM_IMAGE = "nginx-proxy-manager"


def requested(containers):
    return [c for c in containers if c["labels"].get(LABEL)]


def _zone_for(domain, zones):
    matches = [z for z in zones if domain == z or domain.endswith("." + z)]
    return max(matches, key=len) if matches else None


def _cert_for(domain, certs):
    for cert in certs:
        for name in (n.lower() for n in cert.get("domain_names", [])):
            if name == domain or (name.startswith("*.") and "." in domain and domain.split(".", 1)[1] == name[2:]):
                return cert
    return None


def _dns_has(domain, records):
    names = {r["name"] for r in records}
    return domain in names or ("." in domain and "*." + domain.split(".", 1)[1] in names)


def dns_target(records, npm_ip):
    """Wohin neue Namen zeigen: auf das CNAME-Ziel der bestehenden Proxy-Dienste, sonst per A auf NPM."""
    a_records = {r["name"]: r["value"] for r in records if r["type"] == "A"}
    targets = Counter(r["value"] for r in records if r["type"] == "CNAME" and a_records.get(r["value"]) == npm_ip)
    if targets:
        return "CNAME", targets.most_common(1)[0][0]
    return ("A", npm_ip) if npm_ip else (None, None)


def _icon(names):
    for raw in names:
        n = re.sub(r"[^a-z0-9-]+", "-", (raw or "").lower()).strip("-")
        if n and sources.icon_exists(n):
            return f"{n}.png"
    return "mdi-application-outline"


def _group(name, cont, domain, texts, existing_groups):
    category = catalog.category_for(name, cont["image"], [cont["name"], domain.split(".")[0]], texts)
    return catalog.group_for(category, existing_groups) if category else None


def plan(containers, npm, zones, records, certs, editable, npm_ip, default_group, texts=None, existing_groups=()):
    npm_hosts = {d for h in npm for d in h["domains"]}
    npm_cont = next((c for c in containers if c.get("local") and NPM_IMAGE in c["image"]), None)
    dns_type, dns_value = dns_target(records, npm_ip)
    items = []
    for cont in requested(containers):
        labels = cont["labels"]
        domain = host_of(labels[LABEL].strip())
        problems = []

        port = labels.get("homepage-agent.port") or (
            cont["private_ports"][0] if len(cont["private_ports"]) == 1 else None)
        shared = (npm_cont and cont["server"] == npm_cont["server"]
                  and set(npm_cont["networks"]) & set(cont["networks"]) - {"host"})
        if "host" in cont["networks"]:  # network_mode: host – der Dienst lauscht direkt am Host
            forward_host, forward_port = cont.get("host_ip") or cont["host"], port
        elif shared:
            forward_host, forward_port = cont["name"], port
        else:  # NPM erreicht den Container nur über den veröffentlichten Port am Host
            forward_host = cont.get("host_ip") or cont["host"]
            forward_port = cont["port_map"].get(int(port)) if port else (
                cont["ports"][0] if len(cont["ports"]) == 1 else None)
        if not forward_port:
            problems.append("Port unklar – bitte Label `homepage-agent.port` setzen")
        zone = _zone_for(domain, zones)
        if not zone:
            problems.append(f"Keine DNS-Zone in Technitium passt zu `{domain}`")
        if not dns_type:
            problems.append("Ziel für den DNS-Eintrag unbekannt (NPM-IP nicht ermittelbar)")

        cert = _cert_for(domain, certs)
        need_dns = not _dns_has(domain, records)
        need_npm = domain not in npm_hosts
        need_labels = not (labels.get("homepage.href") or labels.get("homepage.name"))
        if not (need_dns or need_npm or need_labels):
            continue

        project = labels.get("com.docker.compose.project", "")
        target = None
        if cont.get("local") and project in editable and labels.get("com.docker.compose.service"):
            target = {"stack": project, "stack_id": editable[project], "service": labels["com.docker.compose.service"]}
        image = cont["image"].split("/")[-1].split(":")[0]
        name, description, icon = catalog.describe(image=cont["image"], container=cont["name"], project=project,
                                                   domain=domain, labels=labels, sources=texts)
        values = {
            "homepage.group": labels.get("homepage.group") or _group(name, cont, domain, texts, existing_groups)
                              or default_group or "Services",
            "homepage.name": labels.get("homepage.name") or name,
            "homepage.href": f"{'https' if cert else 'http'}://{domain}",
            "homepage.icon": labels.get("homepage.icon") or icon or _icon([cont["name"], image, domain.split(".")[0]]),
            "homepage.description": labels.get("homepage.description") or description,
        }
        items.append({
            "id": f"new:{domain}",
            "kind": "provision",
            "name": values["homepage.name"],
            "domain": domain,
            "container": cont["name"],
            "server": cont["server"],
            "problems": problems,
            "dns": {"name": domain, "zone": zone, "type": dns_type, "value": dns_value} if need_dns else None,
            "npm": {"forward_host": forward_host, "forward_port": forward_port,
                    "scheme": labels.get("homepage-agent.scheme", "http"),
                    "certificate_id": cert["id"] if cert else 0,
                    "certificate": ", ".join(cert["domain_names"]) if cert else ""} if need_npm else None,
            "labels": {"target": target, "values": values} if need_labels else None,
        })
    return items


def describe(item):
    lines = []
    if item["dns"]:
        d = item["dns"]
        lines.append(f"• DNS: {d['type']} `{d['name']}` → `{d['value']}` (Zone `{d['zone']}`)")
    if item["npm"]:
        n = item["npm"]
        tls = f"Zertifikat `{n['certificate']}`, HTTPS erzwungen" if n["certificate_id"] else "ohne Zertifikat (nur HTTP)"
        lines.append(f"• NPM: Proxy-Host → `{n['scheme']}://{n['forward_host']}:{n['forward_port']}`, {tls}")
    if item["labels"]:
        t = item["labels"]["target"]
        where = (f"Docker-Labels an `{t['service']}` im Stack `{t['stack']}` (Container startet neu)" if t
                 else "Eintrag in services.yaml (Labels hier nicht möglich)")
        v = item["labels"]["values"]
        lines.append(f"• Homepage: {where} – Gruppe *{v['homepage.group']}*, Icon `{v['homepage.icon']}`")
    return lines


def execute(settings, item):
    """DNS → NPM → Homepage, jeder Schritt einzeln. Liefert (erledigt, Fehler)."""
    done, errors = [], []
    if item["dns"]:
        try:
            sources.technitium_add(settings.technitium_url, settings.technitium_token, item["dns"])
            done.append(f"DNS {item['dns']['type']} {item['domain']}")
        except Exception as exc:
            errors.append(f"DNS: {str(exc)[:150]}")
    if item["npm"]:
        n = item["npm"]
        try:
            session = sources.npm_session(settings.npm_url, settings.npm_user, settings.npm_password)
            sources.npm_create_host(session, settings.npm_url, item["domain"], n["forward_host"], n["forward_port"],
                                    n["scheme"], n["certificate_id"])
            done.append(f"Proxy-Host {item['domain']}")
        except Exception as exc:
            errors.append(f"NPM: {str(exc)[:150]}")
    if item["labels"]:
        t, v = item["labels"]["target"], item["labels"]["values"]
        try:
            if t and settings.portainer_url and settings.portainer_api_key:
                Portainer(settings.portainer_url, settings.portainer_api_key, settings.portainer_endpoint_id) \
                    .set_labels(t["stack_id"], t["service"], {k: val for k, val in v.items() if val})
                done.append(f"Homepage-Labels im Stack {t['stack']}")
            else:
                homepage.add_service(settings.config_dir, settings.data_dir / "backups", v["homepage.group"],
                                     v["homepage.name"], {"href": v["homepage.href"], "icon": v["homepage.icon"],
                                                          "description": v["homepage.description"],
                                                          "server": item["server"], "container": item["container"]})
                done.append("Eintrag in services.yaml")
        except Exception as exc:
            errors.append(f"Homepage: {str(exc)[:150]}")
    return done, errors
