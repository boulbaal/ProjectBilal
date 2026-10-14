"""Configuration from .env. One place, validated once, no magic strings elsewhere."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE_DIR = ROOT / "knowledge"

load_dotenv(ROOT / ".env")


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None or v == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    v = os.getenv(name)
    return int(v) if v else default


def _list(name: str) -> list[str]:
    v = os.getenv(name, "")
    return [x.strip() for x in v.split(",") if x.strip()]


@dataclass(frozen=True)
class Settings:
    # Meta
    meta_app_id: str = os.getenv("META_APP_ID", "")
    meta_app_secret: str = os.getenv("META_APP_SECRET", "")
    meta_access_token: str = os.getenv("META_ACCESS_TOKEN", "")
    meta_phone_number_id: str = os.getenv("META_PHONE_NUMBER_ID", "")
    meta_waba_id: str = os.getenv("META_WABA_ID", "")
    meta_verify_token: str = os.getenv("META_VERIFY_TOKEN", "")
    meta_api_version: str = os.getenv("META_API_VERSION", "v21.0")
    # Mail
    mail_address: str = os.getenv("MAIL_ADDRESS", "")
    mail_provider: str = os.getenv("MAIL_PROVIDER", "imap")
    mail_imap_host: str = os.getenv("MAIL_IMAP_HOST", "")
    mail_imap_port: int = _int("MAIL_IMAP_PORT", 993)
    mail_smtp_host: str = os.getenv("MAIL_SMTP_HOST", "")
    mail_smtp_port: int = _int("MAIL_SMTP_PORT", 587)
    mail_password: str = os.getenv("MAIL_PASSWORD", "")
    mail_poll_seconds: int = max(30, _int("MAIL_POLL_SECONDS", 60))
    # Anthropic
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")
    # Server
    public_domain: str = os.getenv("PUBLIC_DOMAIN", "")
    approval_secret: str = os.getenv("APPROVAL_SECRET", "")
    port: int = _int("PORT", 8000)
    data_dir: Path = Path(os.getenv("DATA_DIR", str(ROOT / "data")))
    # Behaviour
    approver_emails: list[str] = field(default_factory=lambda: _list("APPROVER_EMAILS"))
    dry_run: bool = _bool("DRY_RUN", True)
    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    def apply_provider_defaults(self) -> "Settings":
        """Fill IMAP/SMTP hosts for known providers when left empty."""
        hosts = {
            "gmail": ("imap.gmail.com", "smtp.gmail.com"),
            "microsoft": ("outlook.office365.com", "smtp.office365.com"),
        }
        if self.mail_provider in hosts and not self.mail_imap_host:
            imap, smtp = hosts[self.mail_provider]
            return Settings(**{**self.__dict__, "mail_imap_host": imap, "mail_smtp_host": smtp or self.mail_smtp_host})
        return self

    def missing_required(self) -> list[str]:
        required = {
            "META_APP_SECRET": self.meta_app_secret,
            "META_ACCESS_TOKEN": self.meta_access_token,
            "META_PHONE_NUMBER_ID": self.meta_phone_number_id,
            "META_VERIFY_TOKEN": self.meta_verify_token,
            "MAIL_ADDRESS": self.mail_address,
            "MAIL_IMAP_HOST": self.mail_imap_host,
            "MAIL_SMTP_HOST": self.mail_smtp_host,
            "MAIL_PASSWORD": self.mail_password,
            "ANTHROPIC_API_KEY": self.anthropic_api_key,
            "PUBLIC_DOMAIN": self.public_domain,
            "APPROVAL_SECRET": self.approval_secret,
            "APPROVER_EMAILS": ",".join(self.approver_emails),
        }
        return [k for k, v in required.items() if not v]


settings = Settings().apply_provider_defaults()
