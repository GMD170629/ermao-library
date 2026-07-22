from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.core.time import timestamp_ms_to_iso


def _normalize_timestamps(value: object, key: str | None = None) -> object:
    if isinstance(value, dict):
        return {item_key: _normalize_timestamps(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_timestamps(item) for item in value]
    if key and (key.endswith("At") or key.endswith("_at")):
        return timestamp_ms_to_iso(value) or value
    return value


def ok(data: object, status_code: int = 200) -> JSONResponse:
    return JSONResponse(jsonable_encoder({"ok": True, "data": _normalize_timestamps(data)}), status_code=status_code)


def fail(message: str, status_code: int = 400, details: object | None = None) -> JSONResponse:
    error: dict[str, object] = {"message": message}
    if details is not None:
        error["details"] = details
    return JSONResponse(jsonable_encoder({"ok": False, "error": _normalize_timestamps(error)}), status_code=status_code)
