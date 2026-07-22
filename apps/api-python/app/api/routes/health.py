from fastapi import APIRouter, Depends, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.schemas.responses import ok
from app.services.health import run_system_health_checks

router = APIRouter(tags=["health"])


@router.get("/health")
def health(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    health_status = run_system_health_checks(db, settings)
    status_code = status.HTTP_200_OK if health_status["status"] == "ok" else status.HTTP_503_SERVICE_UNAVAILABLE
    return ok({"service": "shuku-starship", **health_status}, status_code=status_code)


@router.get("/system/health")
def system_health(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    return ok(run_system_health_checks(db, settings))


@router.get("/__db-ping")
def db_ping(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return ok({"database": "ok"})
