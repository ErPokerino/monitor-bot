"""Simple token-based authentication for the POC."""

import secrets

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

router = APIRouter(prefix="/api/auth", tags=["auth"])

_tokens: dict[str, str] = {}
_USERS = {"admin": "123"}


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str


class MeResponse(BaseModel):
    username: str


def validate_token(token: str) -> str | None:
    """Return the username if token is valid, None otherwise."""
    return _tokens.get(token)


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest) -> LoginResponse:
    if body.username not in _USERS or _USERS[body.username] != body.password:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = secrets.token_hex(32)
    _tokens[token] = body.username
    return LoginResponse(token=token)


@router.get("/me", response_model=MeResponse)
def me(authorization: str | None = Header(default=None)) -> MeResponse:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = authorization.removeprefix("Bearer ").strip()
    username = validate_token(token)
    if username is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return MeResponse(username=username)
