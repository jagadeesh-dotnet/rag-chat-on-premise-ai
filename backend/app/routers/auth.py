from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.auth import service
from app.auth.access import load_access
from app.auth.deps import SignedInUser
from app.auth.passwords import PasswordPolicyError
from app.config import settings

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)


@router.post("/login")
def login(request: LoginRequest, response: Response) -> dict:
    try:
        user = service.authenticate(request.username, request.password)
    except service.LoginLocked as locked:
        raise HTTPException(
            status_code=429,
            detail="Too many failed attempts. Try again later.",
            headers={"Retry-After": str(locked.retry_after)},
        ) from None
    if user is None:
        # Same message for unknown users and wrong passwords: it mustn't reveal which usernames exist.
        raise HTTPException(status_code=401, detail="Wrong username or password.")
    response.set_cookie(
        settings.session_cookie,
        service.create_session(user["id"]),
        max_age=settings.session_hours * 3600,
        httponly=True,  # page scripts can't read it, so an XSS bug can't steal the session
        samesite="strict",  # never sent with requests started by other sites (CSRF)
        secure=settings.cookie_secure,
        path="/",
    )
    return load_access(user).to_public()


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response) -> None:
    token = request.cookies.get(settings.session_cookie)
    service.end_session(token, service.user_for_session(token))
    response.delete_cookie(settings.session_cookie, path="/")


@router.get("/me")
def me(user: SignedInUser) -> dict:
    """Works even when the password must be changed, so the frontend knows to ask for it."""
    return load_access(user).to_public()


@router.post("/change-password", status_code=204)
def change_password(user: SignedInUser, request: ChangePasswordRequest) -> None:
    try:
        service.change_password(user, request.current_password, request.new_password)
    except (service.AccountError, PasswordPolicyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
