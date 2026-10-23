"""Einstellungen aus Umgebungsvariablen."""
import os
from dataclasses import dataclass
from pathlib import Path


def _env(name, default=""):
    return os.environ.get(name, default).strip()


def _list(name):
    return [x.strip().lower() for x in _env(name).split(",") if x.strip()]


def _bool(name, default):
    value = _env(name)
    return default if not value else value.lower() in ("1", "true", "yes", "ja", "on")


@dataclass(frozen=True)
class Settings:
    npm_url: str
    npm_user: str
    npm_password: str
    technitium_url: str
    technitium_token: str
    technitium_zones: list
    proxmox_url: str
    proxmox_token_id: str
    proxmox_token_secret: str
    config_dir: Path
    data_dir: Path
    docker_host_ip: str
    slack_bot_token: str
    slack_app_token: str
    slack_channel: str
    schedule: str
    tz: str
    ignore: list
    default_group: str
    portainer_url: str
    portainer_api_key: str
    portainer_endpoint_id: int
    candidate_sources: list
    probe_dns: bool
    run_on_start: bool

    @classmethod
    def from_env(cls):
        return cls(
            npm_url=_env("NPM_URL").rstrip("/"),
            npm_user=_env("NPM_USER"),
            npm_password=_env("NPM_PASSWORD"),
            technitium_url=_env("TECHNITIUM_URL").rstrip("/"),
            technitium_token=_env("TECHNITIUM_TOKEN"),
            technitium_zones=_list("TECHNITIUM_ZONES"),
            proxmox_url=_env("PROXMOX_URL").rstrip("/"),
            proxmox_token_id=_env("PROXMOX_TOKEN_ID"),
            proxmox_token_secret=_env("PROXMOX_TOKEN_SECRET"),
            config_dir=Path(_env("HOMEPAGE_CONFIG_DIR", "/config")),
            data_dir=Path(_env("DATA_DIR", "/data")),
            docker_host_ip=_env("DOCKER_HOST_IP"),
            slack_bot_token=_env("SLACK_BOT_TOKEN"),
            slack_app_token=_env("SLACK_APP_TOKEN"),
            slack_channel=_env("SLACK_CHANNEL_ID"),
            schedule=_env("CHECK_SCHEDULE", "0 8 * * *"),
            tz=_env("TZ", "Europe/Berlin"),
            ignore=_list("IGNORE"),
            default_group=_env("DEFAULT_GROUP"),
            portainer_url=_env("PORTAINER_URL").rstrip("/"),
            portainer_api_key=_env("PORTAINER_API_KEY"),
            portainer_endpoint_id=int(_env("PORTAINER_ENDPOINT_ID", "3")),
            candidate_sources=_list("CANDIDATE_SOURCES") or ["npm"],
            probe_dns=_bool("PROBE_DNS", True),
            run_on_start=_bool("RUN_ON_START", False),
        )
