"""Homepage-Config lesen, prüfen und Einträge ergänzen."""
import datetime
import difflib
import json
import os
import re
import shutil
from pathlib import Path
from urllib.parse import urlparse

import yaml

SERVICE_KEYS = {
    "href", "description", "icon", "server", "container", "widget", "widgets", "siteMonitor", "ping",
    "statusStyle", "showStats", "proxmoxNode", "proxmoxVMID", "proxmoxType", "weight", "id", "target",
    "app", "namespace", "podSelector", "abbr",
}
KEEP_BACKUPS = 30


def slug(text):
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def host_of(url):
    if not url or not isinstance(url, str):
        return ""
    if "://" not in url:
        url = "http://" + url
    return (urlparse(url).hostname or "").lower()


def load_yaml(path):
    path = Path(path)
    return yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else None


def iter_services(groups, parents=()):
    """Alle Dienste aus services.yaml, auch in Untergruppen."""
    for group in groups or []:
        if not isinstance(group, dict):
            continue
        for gname, items in group.items():
            path = parents + (str(gname),)
            for item in items or []:
                if not isinstance(item, dict):
                    continue
                for name, cfg in item.items():
                    if isinstance(cfg, list):
                        yield from iter_services([{name: cfg}], path)
                    else:
                        yield {"group": " / ".join(path), "top": path[0], "name": str(name),
                               "cfg": cfg if isinstance(cfg, dict) else {}}


def group_names(groups):
    return [str(next(iter(g))) for g in groups or [] if isinstance(g, dict) and g]


def lint(entries, docker_servers):
    issues = []
    for e in entries:
        for key in e["cfg"]:
            if key not in SERVICE_KEYS:
                guess = difflib.get_close_matches(key, SERVICE_KEYS, n=1, cutoff=0.6)
                hint = f" – gemeint ist wohl `{guess[0]}`" if guess else ""
                issues.append(f"*{e['name']}*: unbekannter Schlüssel `{key}`{hint}")
        server = e["cfg"].get("server")
        if server and docker_servers is not None and server not in docker_servers:
            issues.append(f"*{e['name']}*: Server `{server}` steht nicht in docker.yaml")
    return issues


def _scalar(value):
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    text = str(value)
    plain = (re.fullmatch(r"[A-Za-z0-9][\w .\-/:@()]*", text) and ": " not in text
             and not text.endswith(":") and yaml.safe_load(text) == text)
    return text if plain else json.dumps(text, ensure_ascii=False)


def render_entry(name, cfg):
    lines = [f"    - {_scalar(name)}:"]
    lines += [f"        {key}: {_scalar(value)}" for key, value in cfg.items() if value not in (None, "")]
    return lines


def add_service(config_dir, backup_dir, group, name, cfg):
    """Hängt einen Dienst an eine Gruppe an – als Text, damit Kommentare und Formatierung bleiben."""
    path = Path(config_dir) / "services.yaml"
    original = path.read_text(encoding="utf-8") if path.exists() else "---\n"
    newline = "\r\n" if "\r\n" in original else "\n"
    lines = original.replace("\r\n", "\n").split("\n")
    while lines and not lines[-1].strip():
        lines.pop()

    if any(e["name"] == name and e["top"] == group for e in iter_services(yaml.safe_load(original))):
        raise ValueError(f"„{name}“ steht schon in der Gruppe „{group}“")

    header = re.compile(rf"""^-\s+["']?{re.escape(group)}["']?\s*:\s*$""")
    start = next((i for i, line in enumerate(lines) if header.match(line)), None)
    block = render_entry(name, cfg)
    if start is None:
        lines += ["", f"- {_scalar(group)}:", *block]
    else:
        end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("-")), len(lines))
        while end > start + 1 and not lines[end - 1].strip():
            end -= 1
        lines[end:end] = ["", *block]
    text = newline.join(lines) + newline

    if not any(e["name"] == name and e["top"] == group for e in iter_services(yaml.safe_load(text))):
        raise ValueError("Eintrag wäre nicht lesbar gewesen – services.yaml bleibt unverändert")

    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    stat = path.stat() if path.exists() else None
    if stat:
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        shutil.copy2(path, backup_dir / f"services-{stamp}.yaml")
        for old in sorted(backup_dir.glob("services-*.yaml"))[:-KEEP_BACKUPS]:
            old.unlink()

    tmp = path.with_name(".services.yaml.tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    if stat:
        os.chmod(tmp, stat.st_mode & 0o777)
        try:
            os.chown(tmp, stat.st_uid, stat.st_gid)
        except (PermissionError, AttributeError):
            pass
    os.replace(tmp, path)
