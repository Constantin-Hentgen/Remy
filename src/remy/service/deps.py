"""FastAPI dependencies: authentication with the shared API key."""

import hmac
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer = HTTPBearer(auto_error=False, description="The service's API key (REMY_API_KEY).")


def require_key(request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> None:
    """Every /v1 call sends ``Authorization: Bearer <REMY_API_KEY>``. Without a configured key, nothing is allowed:
    suggestions spend the operator's Anthropic credit, so an open service is never the default."""
    configured = request.app.state.settings.remy_api_key
    if configured is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "REMY_API_KEY is not set on the server")
    if credentials is None or not hmac.compare_digest(
        credentials.credentials.encode(), configured.get_secret_value().encode()
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing or invalid API key", {"WWW-Authenticate": "Bearer"})
