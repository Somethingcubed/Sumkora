import os
import secrets
from pathlib import Path


def load_local_env(path: str = ".env"):
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


load_local_env()


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def env_bool(name: str, default: bool = False) -> bool:
    value = env(name, "true" if default else "false").lower()
    return value not in {"0", "false", "no", "off"}


AI_PROVIDER = env("AI_PROVIDER", "cxsee_qwen")
APP_ENV = env("APP_ENV", "development")

OPENAI_API_KEY = env("OPENAI_API_KEY")
OPENAI_MODEL = env("OPENAI_MODEL", "gpt-4o-mini")

DEEPSEEK_API_KEY = env("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = env("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = env("DEEPSEEK_MODEL", "deepseek-v4-pro")

OCR_ENABLED = env_bool("OCR_ENABLED", True)
OCR_PROVIDER = env("OCR_PROVIDER", "cxsee_vl")  # cxsee_vl | google_vision | mathpix
OCR_RENDER_DPI = int(env("OCR_RENDER_DPI", "200"))
OCR_PROMPT_VERSION = env("OCR_PROMPT_VERSION", "ocr-math-v2")
OCR_PAGE_CONCURRENCY = max(1, min(8, int(env("OCR_PAGE_CONCURRENCY", "4"))))

CXSEE_API_KEY = env("CXSEE_API_KEY")
CXSEE_BASE_URL = env("CXSEE_BASE_URL", "https://api.cxsee.com")
CXSEE_OCR_MODEL = env("CXSEE_OCR_MODEL", "qwen-vl-ocr-latest")
CXSEE_OCR_FALLBACK_MODEL = env("CXSEE_OCR_FALLBACK_MODEL", "qwen-vl-ocr")
CXSEE_OCR_FALLBACK_MODELS = [
    model.strip()
    for model in env(
        "CXSEE_OCR_FALLBACK_MODELS",
        f"{CXSEE_OCR_FALLBACK_MODEL},qwen3-vl-plus",
    ).split(",")
    if model.strip()
]
CXSEE_GRADING_MODEL = env("CXSEE_GRADING_MODEL")
CXSEE_DIAGNOSIS_MODEL = env("CXSEE_DIAGNOSIS_MODEL")
CXSEE_MARKING_MODEL = env("CXSEE_MARKING_MODEL", CXSEE_GRADING_MODEL or "qwen3-vl-plus")
CXSEE_TIMEOUT_SECONDS = int(env("CXSEE_TIMEOUT_SECONDS", "90"))
CXSEE_MAX_RETRIES = int(env("CXSEE_MAX_RETRIES", "2"))
WHOLE_DOCUMENT_MODEL = env("WHOLE_DOCUMENT_MODEL", "gpt-5.5")
WHOLE_DOCUMENT_REASONING_EFFORT = env(
    "WHOLE_DOCUMENT_REASONING_EFFORT", "medium"
)
WHOLE_DOCUMENT_TIMEOUT_SECONDS = int(
    env("WHOLE_DOCUMENT_TIMEOUT_SECONDS", "540")
)
WHOLE_DOCUMENT_TARGET_SECONDS = int(
    env("WHOLE_DOCUMENT_TARGET_SECONDS", "480")
)
WHOLE_DOCUMENT_COMPACT_TARGET_SECONDS = int(
    env("WHOLE_DOCUMENT_COMPACT_TARGET_SECONDS", "120")
)
WHOLE_DOCUMENT_COMPACT_INITIAL_TIMEOUT_SECONDS = int(
    env("WHOLE_DOCUMENT_COMPACT_INITIAL_TIMEOUT_SECONDS", "70")
)
WHOLE_DOCUMENT_COMPACT_RETRY_TIMEOUT_SECONDS = int(
    env("WHOLE_DOCUMENT_COMPACT_RETRY_TIMEOUT_SECONDS", "45")
)
WHOLE_DOCUMENT_FAST_LONG_TIMEOUT_SECONDS = int(
    env("WHOLE_DOCUMENT_FAST_LONG_TIMEOUT_SECONDS", "110")
)
WHOLE_DOCUMENT_FAST_PRIMARY_MODEL = env(
    "WHOLE_DOCUMENT_FAST_PRIMARY_MODEL", "gpt-5.4-mini"
)
WHOLE_DOCUMENT_FAST_FALLBACK_MODEL = env(
    "WHOLE_DOCUMENT_FAST_FALLBACK_MODEL", "gpt-5.5"
)
WHOLE_DOCUMENT_FAST_ESTIMATE_MAX_PAGES = int(
    env("WHOLE_DOCUMENT_FAST_ESTIMATE_MAX_PAGES", "20")
)
WHOLE_DOCUMENT_FAST_DETAILED_MAX_SCHEME_PAGES = int(
    env("WHOLE_DOCUMENT_FAST_DETAILED_MAX_SCHEME_PAGES", "20")
)
WHOLE_DOCUMENT_FAST_ESTIMATE_RENDER_DPI = int(
    env("WHOLE_DOCUMENT_FAST_ESTIMATE_RENDER_DPI", "110")
)
WHOLE_DOCUMENT_FAST_FEEDBACK_TIMEOUT_SECONDS = int(
    env("WHOLE_DOCUMENT_FAST_FEEDBACK_TIMEOUT_SECONDS", "35")
)
WHOLE_DOCUMENT_OPTIONAL_TIMEOUT_SECONDS = int(
    env("WHOLE_DOCUMENT_OPTIONAL_TIMEOUT_SECONDS", "120")
)
WHOLE_DOCUMENT_MAX_PAGES = int(env("WHOLE_DOCUMENT_MAX_PAGES", "80"))
WHOLE_DOCUMENT_AUDIT_ENABLED = env_bool(
    "WHOLE_DOCUMENT_AUDIT_ENABLED", False
)
WHOLE_DOCUMENT_FEEDBACK_ENABLED = env_bool(
    "WHOLE_DOCUMENT_FEEDBACK_ENABLED", True
)
WHOLE_DOCUMENT_CONTEXT_ENABLED = env_bool(
    "WHOLE_DOCUMENT_CONTEXT_ENABLED", True
)
WHOLE_DOCUMENT_AUDIT_MODEL = env(
    "WHOLE_DOCUMENT_AUDIT_MODEL", WHOLE_DOCUMENT_MODEL
)
WHOLE_DOCUMENT_AUDIT_REASONING_EFFORT = env(
    "WHOLE_DOCUMENT_AUDIT_REASONING_EFFORT", "medium"
)
QUESTION_SOLVER_MODEL = env("QUESTION_SOLVER_MODEL", WHOLE_DOCUMENT_MODEL)
PRACTICE_GENERATION_MODEL = env("PRACTICE_GENERATION_MODEL", "gpt-5.4-mini")
PRACTICE_VALIDATION_MODEL = env(
    "PRACTICE_VALIDATION_MODEL", QUESTION_SOLVER_MODEL
)
QUESTION_SOLVER_TIMEOUT_SECONDS = max(
    15, min(55, int(env("QUESTION_SOLVER_TIMEOUT_SECONDS", "55")))
)

GOOGLE_VISION_API_KEY = env("GOOGLE_VISION_API_KEY")

MATHPIX_APP_ID = env("MATHPIX_APP_ID")
MATHPIX_APP_KEY = env("MATHPIX_APP_KEY")

DB_PATH = env("DB_PATH", "data/app.db")
UPLOAD_DIR = env("UPLOAD_DIR", "data/uploads")
MAX_UPLOAD_BYTES = int(env("MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
COOKIE_SECURE = env_bool("COOKIE_SECURE", APP_ENV == "production")
SESSION_MAX_AGE_SECONDS = int(env("SESSION_MAX_AGE_SECONDS", str(86400 * 7)))
TRUSTED_HOSTS = [
    host.strip()
    for host in env("TRUSTED_HOSTS", "127.0.0.1,localhost,testserver").split(",")
    if host.strip()
]

SECRET_KEY = env("SECRET_KEY")
CONFIG_WARNINGS = []
if not SECRET_KEY:
    SECRET_KEY = secrets.token_urlsafe(32)
    CONFIG_WARNINGS.append(
        "SECRET_KEY is not set. A temporary dev session secret was generated; logins will reset after restart."
    )

if AI_PROVIDER == "cxsee_qwen" and not CXSEE_API_KEY:
    CONFIG_WARNINGS.append(
        "AI_PROVIDER=cxsee_qwen but CXSEE_API_KEY is not set. Vision grading will fail closed and flag submissions."
    )
