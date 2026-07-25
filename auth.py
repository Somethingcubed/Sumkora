from typing import Optional

from fastapi import Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

import config
from db import get_user_by_id, user_has_role

serializer = URLSafeTimedSerializer(config.SECRET_KEY, salt="numera-session-v2")


def create_session_token(user_id: int) -> str:
    return serializer.dumps({"user_id": user_id})


def read_session_token(token: str) -> Optional[int]:
    try:
        data = serializer.loads(token, max_age=config.SESSION_MAX_AGE_SECONDS)
        return data.get("user_id")
    except (BadSignature, SignatureExpired):
        return None


def get_current_user(request: Request):
    token = request.cookies.get("session")
    if not token:
        return None
    user_id = read_session_token(token)
    if not user_id:
        return None
    return get_user_by_id(user_id)


def require_login(request: Request):
    user = get_current_user(request)
    if not user:
        return None
    return user


def require_role(request: Request, role: str):
    user = require_login(request)
    if not user:
        return None
    if user["role"] == role or user_has_role(user["id"], role):
        return user
    return None


def require_researcher(request: Request):
    user = require_login(request)
    if not user or not user_has_role(user["id"], "researcher", "owner"):
        return None
    return user
