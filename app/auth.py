from __future__ import annotations

import jwt
from fastapi import HTTPException

from .config import Settings
from .models import Principal


def authenticate(authorization: str | None, settings: Settings, development_role: str) -> Principal:
    if not settings.is_production:
        return Principal(subject="local-development-user", roles={development_role})
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required.")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        client = jwt.PyJWKClient(f"{settings.entra_issuer.rstrip('/')}/discovery/v2.0/keys")
        signing_key = client.get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            audience=settings.entra_audience,
            issuer=settings.entra_issuer,
        )
    except jwt.PyJWTError as error:
        raise HTTPException(status_code=401, detail="Invalid access token.") from error
    roles = set(claims.get("roles", [])) | set(claims.get("groups", []))
    return Principal(subject=claims.get("oid") or claims.get("sub") or "unknown", roles=roles)
