"""Public contracts exposed by the mobile compatibility capability."""

from app.modules.mobile.domain.compatibility import SERVER_IDENTITY_SETTING_KEY
from app.modules.mobile.infrastructure.server_identity import new_server_identity

__all__ = [
    "SERVER_IDENTITY_SETTING_KEY",
    "new_server_identity",
]
