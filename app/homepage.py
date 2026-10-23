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
    _write(path, text, backup_dir)


def _indent(line):
    return len(line) - len(line.lstrip(" "))


def _group_range(lines, group):
    header = re.compile(rf"""^-\s+["']?{re.escape(group)}["']?\s*:\s*$""")
    start = next((i for i, line in enumerate(lines) if header.match(line)), None)
    if start is None:
        return None, None
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("-")), len(lines))
    return start, end


def update_service(config_dir, backup_dir, group, name, new_name=None, description=None, new_group=None):
    """Name/Beschreibung eines Eintrags ändern und ihn ggf. in eine andere Gruppe verschieben – als Text,
    damit der Rest der Datei Zeichen für Zeichen bleibt."""
    path = Path(config_dir) / "services.yaml"
    original = path.read_text(encoding="utf-8")
    newline = "\r\n" if "\r\n" in original else "\n"
    lines = original.replace("\r\n", "\n").split("\n")

    start, end = _group_range(lines, group)
    if start is None:
        raise ValueError(f"Gruppe „{group}“ nicht gefunden")
    entry_re = re.compile(rf"""^(\s+)-\s+["']?{re.escape(name)}["']?\s*:\s*$""")
    pos = next((i for i in range(start + 1, end) if entry_re.match(lines[i])), None)
    if pos is None:
        raise ValueError(f"„{name}“ nicht in Gruppe „{group}“ gefunden")
    indent = _indent(lines[pos])
    stop = next((i for i in range(pos + 1, end) if lines[i].strip() and _indent(lines[i]) <= indent), end)
    while stop > pos + 1 and not lines[stop - 1].strip():
        stop -= 1
    block = lines[pos:stop]
    child = next((_indent(b) for b in block[1:] if b.strip()), indent + 4)

    if description is not None:
        desc_line = f"{' ' * child}description: {_scalar(description)}"
        idx = next((i for i, b in enumerate(block) if i and _indent(b) == child
                    and b.strip().startswith("description:")), None)
        if idx is None:
            href = next((i for i, b in enumerate(block) if i and _indent(b) == child
                         and b.strip().startswith("href:")), 0)
            block.insert(href + 1, desc_line)
        else:
            block[idx] = desc_line
    final_name = new_name or name
    if new_name:
        block[0] = f"{' ' * indent}- {_scalar(new_name)}:"

    if new_group and new_group != group:
        cut_from = pos - 1 if pos - 1 > start and not lines[pos - 1].strip() else pos
        del lines[cut_from:stop]
        target_start, target_end = _group_range(lines, new_group)
        if target_start is None:
            while lines and not lines[-1].strip():
                lines.pop()
            lines += ["", f"- {_scalar(new_group)}:", *block]
        else:
            while target_end > target_start + 1 and not lines[target_end - 1].strip():
                target_end -= 1
            lines[target_end:target_end] = ["", *block]
    else:
        lines[pos:stop] = block
    text = newline.join(lines)
    if not text.endswith(newline):
        text += newline

    wanted_group = new_group or group
    entries = list(iter_services(yaml.safe_load(text)))
    if not any(e["name"] == final_name and e["top"] == wanted_group for e in entries):
        raise ValueError("Ergebnis wäre nicht lesbar gewesen – services.yaml bleibt unverändert")
    if description is not None and not any(e["name"] == final_name and e["cfg"].get("description") == description
                                           for e in entries):
        raise ValueError("Beschreibung kam nicht an – services.yaml bleibt unverändert")
    _write(path, text, backup_dir)


def _write(path, text, backup_dir):
    """Sicherung anlegen, dann atomar schreiben und Besitzer/Rechte der alten Datei übernehmen."""
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
