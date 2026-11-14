"""FastAPI dependencies: who is calling, and what may they do.

Use the type aliases at the bottom in endpoints:  def endpoint(access: CurrentAccess) -> ...
"""

from typing import Annotated

from fastapi import Depends, HTTPException, Request

from app.auth import service
from app.auth.access import Access, load_access
from app.config import settings


def signed_in(request: Request) -> dict:
    """The user behind the session cookie, or 401."""
    user = service.user_for_session(request.cookies.get(settings.session_cookie))
    if user is None:
        raise HTTPException(status_code=401, detail="Not signed in")
    return user


SignedInUser = Annotated[dict, Depends(signed_in)]


def current_access(user: SignedInUser) -> Access:
    """The signed-in user's permissions. A temporary password must be changed first (403)."""
    access = load_access(user)
    if access.must_change_password:
        raise HTTPException(status_code=403, detail="password_change_required")
    return access


CurrentAccess = Annotated[Access, Depends(current_access)]


def require_admin(access: CurrentAccess) -> Access:
    if not access.is_admin:
        raise HTTPException(status_code=403, detail="Admins only")
    return access


AdminAccess = Annotated[Access, Depends(require_admin)]
