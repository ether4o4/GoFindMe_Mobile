"""Auth endpoints: one-time setup, login, logout, identity."""
from __future__ import annotations

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from . import db, security
from .config import settings

router = APIRouter(prefix="/api", tags=["auth"])


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


def _set_cookie(request: Request, response: Response, token: str) -> None:
    response.set_cookie(
        security.COOKIE_NAME, token,
        max_age=settings().token_ttl_days * 86400,
        httponly=True, samesite="strict",
        secure=(request.url.scheme == "https"), path="/",
    )


@router.get("/auth/status")
def auth_status() -> dict:
    return {"setup_complete": security.setup_complete()}


@router.post("/auth/setup")
def auth_setup(creds: Credentials, request: Request, response: Response) -> dict:
    security.create_user(creds.username, creds.password)
    res = security.login(creds.username, creds.password)
    _set_cookie(request, response, res["token"])
    return res


@router.post("/auth/login")
def auth_login(creds: Credentials, request: Request, response: Response) -> dict:
    res = security.login(creds.username, creds.password)
    _set_cookie(request, response, res["token"])
    return res


@router.post("/auth/logout")
async def auth_logout(request: Request, response: Response) -> dict:
    token = request.cookies.get(security.COOKIE_NAME)
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    if token:
        security.logout(token)
    response.delete_cookie(security.COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
async def me(_t: str = security.Auth) -> dict:
    row = db.query_one("SELECT username, created_at FROM app_user WHERE id=1")
    return {"username": row["username"] if row else None,
            "created_at": row["created_at"] if row else None}
