from typing import Optional

from fastapi import Request
from itsdangerous import BadSignature, URLSafeSerializer

import config
from db import get_user_by_id

serializer = URLSafeSerializer(config.SECRET_KEY, salt="igcse-session")


def create_session_token(user_id: int) -> str:
    return serializer.dumps({"user_id": user_id})


def read_session_token(token: str) -> Optional[int]:
    try:
        data = serializer.loads(token)
        return data.get("user_id")
    except BadSignature:
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
    if not user or user["role"] != role:
        return None
    return user
