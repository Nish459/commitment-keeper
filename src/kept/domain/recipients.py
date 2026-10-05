"""Who Kept may email. Pure rules, so they are easy to test and hard to get wrong."""

from collections.abc import Collection
from email.utils import parseaddr


def normalize_address(address: str) -> str | None:
    """Return a bare lowercase address, or None if it is not a single plain address."""
    if any(ch in address for ch in "\r\n,;<> "):
        return None
    _, parsed = parseaddr(address)
    local, _, domain = parsed.partition("@")
    if parsed != address or not local or "." not in domain:
        return None
    return parsed.lower()


def is_recipient_allowed(address: str, allowed: Collection[str], sender: str) -> bool:
    """Allowed entries are full addresses or '@domain'. With none configured, only the sender."""
    normalized = normalize_address(address)
    if normalized is None:
        return False
    entries = {entry.lower() for entry in allowed} or {sender.lower()}
    domain = "@" + normalized.partition("@")[2]
    return normalized in entries or domain in entries
