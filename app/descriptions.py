"""Kurzbeschreibungen aus gepflegten Quellen: awesome-selfhosted (Liste, CC BY-SA 3.0), dann Docker Hub."""
import logging
import re
import time
from pathlib import Path

import requests

from .homepage import slug

log = logging.getLogger(__name__)
AWESOME_URL = "https://raw.githubusercontent.com/awesome-selfhosted/awesome-selfhosted/master/README.md"
CACHE_DAYS = 7
MAX_LEN = 80
ENTRY = re.compile(r"^\s*- \[(?P<name>[^\]]+)\]\((?P<url>[^)]+)\)\s*(?:`[^`]*`\s*)?- (?P<desc>.+?)(?:\s*\(\[|\s*`|$)")
# Docker-Hub-Texte ohne Inhalt („Docker container for X“, „Official image of …“) → lieber Katalog
NO_CONTENT = re.compile(r"^(a |an |the )?(docker|container|image)\b|\b(docker (container|image)|container for|"
                        r"image for|official image)\b", re.IGNORECASE)
REPO = re.compile(r"https://(?:github\.com|gitlab\.com|codeberg\.org)/([\w.-]+/[\w.-]+)")


def shorten(text, limit=MAX_LEN):
    """Ein Satz, ohne Aufzählungen und Vergleiche, höchstens ~80 Zeichen."""
    text = " ".join(text.split()).rstrip(".")
    for cut in (", such as", ", similar to", ", like ", " - ", ". "):
        if cut in text:
            text = text.split(cut)[0]
    if len(text) <= limit:
        return text
    head = text[:limit]
    head = head.rsplit(", ", 1)[0] if ", " in head else head.rsplit(" ", 1)[0]
    return re.sub(r"\s+(and|or|with|for|of|to|the|a|an)$", "", head) + " …"


class Descriptions:
    def __init__(self, cache_dir):
        self.cache = Path(cache_dir) / "awesome-selfhosted.md"
        self.by_repo, self.by_slug, self.hub = {}, {}, {}
        self._load()

    def _load(self):
        text = ""
        fresh = self.cache.exists() and time.time() - self.cache.stat().st_mtime < CACHE_DAYS * 86400
        if not fresh:
            try:
                r = requests.get(AWESOME_URL, timeout=20)
                r.raise_for_status()
                self.cache.parent.mkdir(parents=True, exist_ok=True)
                self.cache.write_text(r.text, encoding="utf-8")
            except requests.RequestException as exc:
                log.warning("awesome-selfhosted nicht ladbar (%s) – nutze Zwischenspeicher, falls vorhanden", exc)
        if self.cache.exists():
            text = self.cache.read_text(encoding="utf-8")
        section = ""
        for line in text.splitlines():
            if line.startswith("#"):
                section = line.lstrip("#").strip()  # Rubrik, z. B. „Media Streaming - Video Streaming“
                continue
            m = ENTRY.match(line)
            if not m:
                continue
            entry = (shorten(m["desc"]), section)
            for repo in REPO.findall(line):
                self.by_repo.setdefault(repo.lower().removesuffix(".git"), entry)
                self.by_slug.setdefault(slug(repo.split("/")[1]), entry)
            self.by_slug.setdefault(slug(re.sub(r"\s+by\s+.*$", "", m["name"])), entry)

    def _find(self, image, keys):
        path = _image_path(image)
        if path in self.by_repo:
            return self.by_repo[path]
        return next((self.by_slug[slug(k)] for k in keys if slug(k) in self.by_slug), ("", ""))

    def awesome(self, image="", keys=()):
        return self._find(image, keys)[0]

    def section(self, image="", keys=()):
        return self._find(image, keys)[1]

    def docker_hub(self, image):
        path = _image_path(image)
        first = (image or "").split("/")[0]
        if not path or ("." in first or ":" in first) and "/" in (image or ""):
            return ""  # liegt nicht auf Docker Hub (ghcr.io, lscr.io …)
        if "/" not in path:
            path = "library/" + path
        if path not in self.hub:
            try:
                r = requests.get(f"https://hub.docker.com/v2/repositories/{path}/", timeout=5)
                text = shorten(r.json().get("description") or "") if r.ok else ""
                self.hub[path] = "" if NO_CONTENT.search(text) else text
            except (requests.RequestException, ValueError):
                self.hub[path] = ""
        return self.hub[path]


def _image_path(image):
    """`ghcr.io/gethomepage/homepage:latest` → `gethomepage/homepage`."""
    parts = (image or "").split("@")[0].split("/")
    if len(parts) > 1 and ("." in parts[0] or ":" in parts[0]):
        parts = parts[1:]
    return "/".join(parts).split(":")[0].lower()
