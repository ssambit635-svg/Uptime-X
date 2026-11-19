from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    auth_rate_limit,
    current_user,
    password_hasher,
    revoke_request_sessions,
    start_session,
    wants_preview_session,
)
from app.models.entities import AuthSession, User, utcnow
from app.schemas.auth import AuthResponse, Credentials, PreviewSessionOut, UserOut

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register", response_model=AuthResponse, response_model_exclude_none=True, status_code=201
)
def register(
    credentials: Credentials,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> AuthResponse:
    auth_rate_limit(request, "register", 10)
    user = User(
        email=str(credentials.email), password_hash=password_hasher.hash(credentials.password)
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise AppError(409, "EMAIL_IN_USE", "An account with this email already exists.") from exc
    preview = wants_preview_session(request)
    credential = start_session(db, user, response, preview_transport=preview)
    result = AuthResponse.model_validate(user)
    if preview:
        result.preview_session = PreviewSessionOut(
            token=credential.token, expires_at=credential.expires_at
        )
    return result


@router.post("/login", response_model=AuthResponse, response_model_exclude_none=True)
def login(
    credentials: Credentials,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> AuthResponse:
    auth_rate_limit(request, "login", 20)
    user = db.scalar(select(User).where(User.email == str(credentials.email)))
    password_hash = user.password_hash if user else DUMMY_PASSWORD_HASH
    valid, replacement_hash = password_hasher.verify_and_update(credentials.password, password_hash)
    if not valid or user is None:
        raise AppError(401, "INVALID_CREDENTIALS", "The email or password is incorrect.")
    if replacement_hash:
        user.password_hash = replacement_hash
    # Rotate the current browser's session when signing in again.
    revoke_request_sessions(db, request)
    db.execute(delete(AuthSession).where(AuthSession.expires_at <= utcnow()))
    preview = wants_preview_session(request)
    credential = start_session(db, user, response, preview_transport=preview)
    result = AuthResponse.model_validate(user)
    if preview:
        result.preview_session = PreviewSessionOut(
            token=credential.token, expires_at=credential.expires_at
        )
    return result


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> User:
    return user


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> None:
    settings = get_settings()
    revoke_request_sessions(db, request)
    db.commit()
    response.delete_cookie(
        settings.cookie_name,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite=settings.cookie_samesite,
    )
    if settings.embedded_preview:
        response.headers["set-cookie"] += "; Partitioned"
