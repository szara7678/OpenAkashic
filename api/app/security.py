from fastapi import Header, HTTPException, status

from app.config import get_settings


def require_write_key(x_openakashic_key: str | None = Header(default=None)) -> None:
    expected = get_settings().write_api_key
    if not expected:
        return
    if x_openakashic_key != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid X-OpenAkashic-Key",
        )
