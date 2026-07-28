"""Composition wiring for legacy HTTP routes.

Remove each export when the corresponding route moves into its capability
presentation router.  Compatibility delivery code must not deep-import
infrastructure adapters directly.
"""

from app.modules.imports.infrastructure import import_http as import_http_store
from app.modules.library.infrastructure import dashboard as library_dashboard
from app.modules.library.infrastructure import deletion as library_deletion
from app.modules.library.infrastructure import facet_queries as library_facet_queries
from app.modules.library.infrastructure import join_queries as library_join_queries
from app.modules.library.infrastructure import operations as library_operation_store
from app.modules.library.infrastructure import projections as library_projections
from app.modules.library.infrastructure import storage as library_storage
from app.modules.library.infrastructure import works as library_works
from app.modules.media.infrastructure import page_index as media_page_index
from app.modules.organize.infrastructure import job_queries as organize_job_queries
from app.modules.organize.infrastructure import jobs as organize_jobs
from app.modules.organize.infrastructure import runs as organize_runs
from app.modules.shelf.infrastructure import shelves as shelf_store

__all__ = [
    "import_http_store",
    "library_dashboard",
    "library_deletion",
    "library_facet_queries",
    "library_join_queries",
    "library_operation_store",
    "library_projections",
    "library_storage",
    "library_works",
    "media_page_index",
    "organize_job_queries",
    "organize_jobs",
    "organize_runs",
    "shelf_store",
]
