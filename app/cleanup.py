"""Dienst aufräumen: Proxy-Host in NPM und DNS-Einträge in Technitium löschen – mit Sicherung."""
import datetime
import json
import re

from . import sources


def plan(settings, hosts):
    """Frisch abfragen, was zu den Hostnamen gehört. Gelöscht wird erst mit execute()."""
    hosts = {h.lower() for h in hosts}
    result = {"npm": [], "dns": [], "errors": []}
    if settings.npm_url:
        try:
            session = sources.npm_session(settings.npm_url, settings.npm_user, settings.npm_password)
            result["npm"] = [h for h in sources.npm_raw_hosts(session, settings.npm_url)
                             if hosts & {d.lower() for d in h.get("domain_names", [])}]
        except Exception as exc:
            result["errors"].append(f"NPM: {str(exc)[:150]}")
    if settings.technitium_url:
        try:
            _, records = sources.technitium_records(settings.technitium_url, settings.technitium_token,
                                                    settings.technitium_zones)
            result["dns"] = [r for r in records if r["name"] in hosts and not r["wildcard"]]
        except Exception as exc:
            result["errors"].append(f"Technitium: {str(exc)[:150]}")
    return result


def describe(p):
    lines = []
    for h in p["npm"]:
        target = f"{h.get('forward_host')}:{h.get('forward_port')}"
        lines.append(f"• Proxy-Host #{h['id']}: {', '.join(h['domain_names'])} → {target}")
    for r in p["dns"]:
        lines.append(f"• DNS {r['type']} {r['name']} → {r['value']} (Zone {r['zone']})")
    return lines


def execute(settings, p, label):
    """Sichert alles als JSON nach data/deleted/ und löscht dann. Liefert (gelöscht, Fehler)."""
    backup_dir = settings.data_dir / "deleted"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    name = re.sub(r"[^a-z0-9-]+", "-", label.lower()).strip("-") or "dienst"
    (backup_dir / f"{stamp}-{name}.json").write_text(
        json.dumps({"npm_proxy_hosts": p["npm"], "dns_records": p["dns"]}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    done, errors = [], []
    if p["npm"]:
        try:
            session = sources.npm_session(settings.npm_url, settings.npm_user, settings.npm_password)
            for h in p["npm"]:
                try:
                    sources.npm_delete_host(session, settings.npm_url, h["id"])
                    done.append(f"Proxy-Host {', '.join(h['domain_names'])}")
                except Exception as exc:
                    errors.append(f"Proxy-Host #{h['id']}: {str(exc)[:120]}")
        except Exception as exc:
            errors.append(f"NPM-Anmeldung: {str(exc)[:120]}")
    for r in p["dns"]:
        try:
            sources.technitium_delete(settings.technitium_url, settings.technitium_token, r)
            done.append(f"DNS {r['type']} {r['name']}")
        except Exception as exc:
            errors.append(f"DNS {r['name']}: {str(exc)[:120]}")
    return done, errors
