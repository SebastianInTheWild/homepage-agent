"""Lebt der Dienst noch? Proxy-Ziel (Container, VM, IP:Port) und Aufruf über die Domain – mit Empfehlung."""
import socket
from concurrent.futures import ThreadPoolExecutor

import requests

from . import sources

ACTIVE, CHECK, LEFTOVER = "active", "check", "leftover"
TEXT = {
    ACTIVE: ":large_green_circle: *Empfehlung: Eintragen* – der Dienst läuft",
    CHECK: ":large_yellow_circle: *Empfehlung: Prüfen* – nicht eindeutig",
    LEFTOVER: ":red_circle: *Empfehlung: Löschen* – sieht nach Resten einer alten Konfiguration aus",
}


def http_check(domain):
    """→ (Statuscode oder None, Fehlertext). 502/504 von NPM bedeutet: Ziel antwortet nicht."""
    for scheme in ("https", "http"):
        try:
            r = requests.get(f"{scheme}://{domain}", timeout=6, verify=False, allow_redirects=True)
            return r.status_code, ""
        except requests.exceptions.SSLError:
            continue
        except requests.exceptions.ConnectionError as exc:
            text = str(exc)
            if "NameResolution" in text or "Name or service not known" in text or "getaddrinfo" in text:
                return None, "Domain löst nicht auf (kein DNS-Eintrag)"
            return None, "keine Verbindung"
        except requests.exceptions.Timeout:
            return None, "Zeitüberschreitung"
        except requests.RequestException as exc:
            return None, str(exc)[:80]
    return None, "TLS-Fehler"


def tcp_open(host, port):
    try:
        with socket.create_connection((host, int(port)), timeout=3):
            return True
    except (OSError, ValueError):
        return False


def assess(c, containers_by_name, guests_by_vmid, http):
    """Bewertung eines Kandidaten → {"verdict": active|check|leftover, "reasons": [...]}."""
    reasons, backend = [], None  # backend: True = läuft, False = weg/gestoppt, None = unbekannt
    fwd = c.forward or {}
    if c.container:
        backend = True
        reasons.append(f"Container `{c.container}` läuft")
    elif fwd.get("host"):
        host, port = fwd["host"], fwd.get("port")
        cont = containers_by_name.get(host)
        if cont and cont["state"] != "running":
            backend = False
            reasons.append(f"Container `{host}` ist gestoppt ({cont['status'] or cont['state']})")
        elif not cont and not sources.is_ip(host) and "." not in host:
            backend = False
            reasons.append(f"Container `{host}` gibt es nicht mehr")
        elif port:
            backend = tcp_open(host, port)
            reasons.append(f"Ziel `{host}:{port}` " + ("antwortet" if backend else "antwortet nicht"))
    vmid = (c.proxmox or {}).get("proxmoxVMID")
    if vmid in guests_by_vmid:
        running = guests_by_vmid[vmid]["running"]
        reasons.append(f"VM/LXC {vmid} " + ("läuft" if running else "ist gestoppt"))
        backend = running if backend is None else backend and running

    status, error = http
    web_ok = status is not None and status < 500
    reasons.append(f"Aufruf: HTTP {status}" + (" (Ziel antwortet nicht)" if status in (502, 503, 504) else "")
                   if status else f"Aufruf: {error}")

    if web_ok and backend is not False:
        verdict = ACTIVE
    elif not web_ok and (backend is False or status in (502, 504) or "DNS" in error):
        verdict = LEFTOVER
    else:
        verdict = CHECK
    return {"verdict": verdict, "reasons": reasons}


def assess_all(candidates, all_containers, guests):
    by_name = {}
    for cont in all_containers:  # laufende vor gestoppten, falls Namen doppelt vorkommen
        if cont["name"] not in by_name or cont["state"] == "running":
            by_name[cont["name"]] = cont
    by_vmid = {g["vmid"]: g for g in guests}
    todo = [c for c in candidates if c.hosts]
    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(lambda c: http_check(c.hosts[0]), todo))
    for c, http in zip(todo, results):
        c.health = assess(c, by_name, by_vmid, http)
