import hashlib
import secrets
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from fastapi import Depends, Request, Response
from pwdlib import PasswordHash
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import AppError
from app.models.entities import AuthSession, User, utcnow

password_hasher = PasswordHash.recommended()
# Spend the same password-verification work for existing and nonexistent accounts.
DUMMY_PASSWORD_HASH = password_hasher.hash(secrets.token_urlsafe(32))


def digest_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


PREVIEW_SESSION_HEADER = "X-UptimeX-Preview-Session"


@dataclass(frozen=True)
class SessionCredential:
    token: str = field(repr=False)
    expires_at: datetime


def wants_preview_session(request: Request) -> bool:
    return (
        get_settings().embedded_preview
        and request.headers.get("X-UptimeX-Session-Mode") == "preview"
    )


def request_session_token(request: Request) -> str | None:
    settings = get_settings()
    # Only the explicitly enabled, non-production preview accepts this transport.
    if settings.embedded_preview and PREVIEW_SESSION_HEADER in request.headers:
        return request.headers[PREVIEW_SESSION_HEADER]
    return request.cookies.get(settings.cookie_name)


def revoke_request_sessions(db: Session, request: Request) -> None:
    settings = get_settings()
    tokens = [request.cookies.get(settings.cookie_name)]
    if settings.embedded_preview:
        tokens.append(request.headers.get(PREVIEW_SESSION_HEADER))
    digests = {digest_token(token) for token in tokens if token and len(token) <= 128}
    if digests:
        db.execute(delete(AuthSession).where(AuthSession.token_digest.in_(digests)))


def start_session(
    db: Session, user: User, response: Response, *, preview_transport: bool = False
) -> SessionCredential:
    settings = get_settings()
    token = secrets.token_urlsafe(32)
    lifetime = (
        timedelta(minutes=settings.preview_session_minutes)
        if preview_transport and settings.embedded_preview
        else timedelta(hours=settings.session_hours)
    )
    expires_at = utcnow() + lifetime
    db.add(AuthSession(token_digest=digest_token(token), user_id=user.id, expires_at=expires_at))
    db.commit()
    response.set_cookie(
        key=settings.cookie_name,
        value=token,
        max_age=int(lifetime.total_seconds()),
        path="/",
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
    )
    if settings.embedded_preview:
        # Python 3.11's cookie API predates CHIPS; append the standardized attribute.
        response.headers["set-cookie"] += "; Partitioned"
    return SessionCredential(token=token, expires_at=expires_at)


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request_session_token(request)
    if not token or len(token) > 128:
        raise AppError(401, "UNAUTHENTICATED", "Please sign in to your workspace.")
    user = db.scalar(
        select(User)
        .join(AuthSession, AuthSession.user_id == User.id)
        .where(
            AuthSession.token_digest == digest_token(token),
            AuthSession.expires_at > utcnow(),
        )
    )
    if user is None:
        raise AppError(401, "UNAUTHENTICATED", "Your session has expired. Please sign in again.")
    return user


class RateLimiter:
    """Bounded, single-process login guard. Use shared limits before multi-replica launch."""

    def __init__(self) -> None:
        self._buckets: OrderedDict[tuple[str, str], deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def check(self, scope: str, key: str, *, limit: int, window: int) -> None:
        now = time.monotonic()
        bucket_key = (scope, key)
        with self._lock:
            bucket = self._buckets.setdefault(bucket_key, deque())
            self._buckets.move_to_end(bucket_key)
            while bucket and bucket[0] <= now - window:
                bucket.popleft()
            if len(bucket) >= limit:
                retry = max(1, int(window - (now - bucket[0])) + 1)
                raise AppError(
                    429,
                    "RATE_LIMITED",
                    "Too many attempts. Please try again in a few minutes.",
                    {"Retry-After": str(retry)},
                )
            bucket.append(now)
            while len(self._buckets) > 10_000:
                self._buckets.popitem(last=False)


def auth_rate_limit(request: Request, scope: str, limit: int) -> None:
    # Do not trust caller-supplied X-Forwarded-For headers.
    address = request.client.host if request.client else "unknown"
    request.app.state.rate_limiter.check(scope, address, limit=limit, window=600)
