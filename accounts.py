import hashlib
import hmac
import re
import secrets

import config


USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{3,24}$")
RESERVED_USERNAMES = {
    "admin",
    "administrator",
    "api",
    "help",
    "login",
    "moderator",
    # Keep the previous product name reserved so it cannot be used to
    # impersonate historical support links or accounts.
    "numera",
    "owner",
    "research",
    "researcher",
    "root",
    "signup",
    "staff",
    "sumkora",
    "support",
    "system",
    "teacher",
}


def normalize_username(value: str) -> str:
    return (value or "").strip().lower()


def validate_username(value: str) -> tuple[str | None, str | None]:
    trimmed = (value or "").strip()
    normalized = trimmed.lower()
    if any(character.isspace() for character in trimmed):
        return None, "Usernames cannot contain spaces."
    if not USERNAME_PATTERN.fullmatch(trimmed):
        return None, "Use 3–24 letters, numbers, underscores, or hyphens."
    if normalized in RESERVED_USERNAMES:
        return None, "Please choose a different username."
    return normalized, None


def validate_password(password: str) -> str | None:
    if len(password or "") < 8:
        return "Use at least 8 characters."
    if len(password) > 128:
        return "Use no more than 128 characters."
    return None


def generate_recovery_code() -> str:
    raw = secrets.token_hex(12).upper()
    return "-".join(raw[index : index + 4] for index in range(0, len(raw), 4))


def normalize_recovery_code(value: str) -> str:
    return "".join(character for character in (value or "").upper() if character.isalnum())


def recovery_code_hash(value: str) -> str:
    normalized = normalize_recovery_code(value)
    return hmac.new(
        config.SECRET_KEY.encode("utf-8"),
        normalized.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def recovery_code_matches(value: str, stored_hash: str | None) -> bool:
    if not stored_hash:
        return False
    return hmac.compare_digest(recovery_code_hash(value), stored_hash)


def count_label(count: int, singular: str, plural: str | None = None) -> str:
    label = singular if count == 1 else (plural or f"{singular}s")
    return f"{count} {label}"


def student_explanation(value: str | None) -> str:
    text = value or ""
    replacements = {
        "Auto-check": "The analysis",
        "extracted student text": "your completed work",
        "extracted text": "your completed work",
        "Human review is recommended": "Review your working",
        "human review of the uploaded work is recommended": "check your completed work",
        "without a vision-capable model": "from the available evidence",
    }
    for source, replacement in replacements.items():
        text = text.replace(source, replacement)
    return text
