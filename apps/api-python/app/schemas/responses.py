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


def ok(
    data: object,
    status_code: int = 200,
    *,
    normalize_timestamps: bool = True,
) -> JSONResponse:
    payload = _normalize_timestamps(data) if normalize_timestamps else data
    return JSONResponse(jsonable_encoder({"ok": True, "data": payload}), status_code=status_code)


def fail(
    message: str,
    status_code: int = 400,
    details: object | None = None,
    *,
    code: str | None = None,
    params: dict[str, object] | None = None,
) -> JSONResponse:
    error: dict[str, object] = {"message": message}
    if code is not None:
        error["code"] = code
    if params is not None:
        error["params"] = params
    if details is not None:
        error["details"] = details
    return JSONResponse(jsonable_encoder({"ok": False, "error": _normalize_timestamps(error)}), status_code=status_code)
