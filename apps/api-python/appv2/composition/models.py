"""Import every ORM table exactly once for Alembic metadata discovery."""

from appv2.modules.accounts.infrastructure import models as accounts_models
from appv2.modules.catalog.infrastructure import models as catalog_models
from appv2.modules.delivery.infrastructure import models as delivery_models
from appv2.modules.discovery.infrastructure import models as discovery_models
from appv2.modules.ingestion.infrastructure import models as ingestion_models
from appv2.modules.metadata.infrastructure import models as metadata_models
from appv2.modules.operations.infrastructure import models as operations_models
from appv2.modules.reading.infrastructure import models as reading_models

__all__ = [
    "accounts_models",
    "catalog_models",
    "delivery_models",
    "discovery_models",
    "ingestion_models",
    "metadata_models",
    "operations_models",
    "reading_models",
]
