from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse


def ok(data: object, status_code: int = 200) -> JSONResponse:
    return JSONResponse(jsonable_encoder({"ok": True, "data": data}), status_code=status_code)


def fail(message: str, status_code: int = 400, details: object | None = None) -> JSONResponse:
    error: dict[str, object] = {"message": message}
    if details is not None:
        error["details"] = details
    return JSONResponse(jsonable_encoder({"ok": False, "error": error}), status_code=status_code)
