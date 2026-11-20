"""Wire the system proxy API to the owned settings store and outbound sender."""

from sqlalchemy.orm import Session

from app.bootstrap.outbound_http import outbound_opener
from app.db.session import release_read_transaction
from app.modules.system.application.network_proxy import StoredProxy
from app.modules.system.domain.network_proxy import ProxyProbeResult
from app.modules.system.infrastructure.network_proxy import (
    read_network_proxy,
    resolve_network_proxy,
    save_network_proxy,
)
from app.modules.system.infrastructure.network_proxy_probe import probe_network_proxy

__all__ = ["read_network_proxy", "save_network_proxy", "test_network_proxy"]


def test_network_proxy(db: Session, payload: StoredProxy) -> list[ProxyProbeResult]:
    snapshot = resolve_network_proxy(db, payload)
    release_read_transaction(db)
    return probe_network_proxy(snapshot, lambda: outbound_opener(snapshot=snapshot))
