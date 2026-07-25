from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from appv2.modules.catalog.application import CatalogNotFound, CatalogService
from appv2.modules.catalog.contracts import CatalogImport
from appv2.modules.delivery.application import DeliveryNotFound, DeliveryService
from appv2.modules.discovery.application import DiscoveryNotFound, DiscoveryService
from appv2.modules.ingestion.application import IngestionNotFound, IngestionService
from appv2.modules.metadata.application import MetadataNotFound, MetadataService
from appv2.modules.metadata.contracts import MetadataCandidate, MetadataPatch
from appv2.modules.operations.application import OperationsNotFound, OperationsService
from appv2.modules.reading.application import (
    LocationClaimConflict,
    ProgressConflict,
    ReadingNotFound,
    ReadingService,
)


class FakeUnitOfWork:
    def __init__(self, repository_name: str) -> None:
        setattr(self, repository_name, MagicMock())
        self.commits = 0

    def __enter__(self) -> FakeUnitOfWork:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        return None


def test_catalog_service_complete_success_and_failure_surface() -> None:
    unit = FakeUnitOfWork("catalog")
    repository = unit.catalog
    covers = MagicMock()
    service = CatalogService(lambda: unit, covers)
    work_id = uuid.uuid4()
    edition_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    shelf_id = uuid.uuid4()
    category_id = uuid.uuid4()
    work = SimpleNamespace(
        id=work_id,
        title="Book",
        author="Author",
        media_type="book",
        cover_key=f"{work_id}/cover.webp",
    )
    edition = SimpleNamespace(id=edition_id, work_id=work_id)
    shelf = SimpleNamespace(id=shelf_id, kind="manual")
    category = SimpleNamespace(id=category_id)

    repository.list_works.return_value = ([work], 1)
    assert service.list_works(
        page=2,
        page_size=10,
        query="book",
        media_type="book",
        status="active",
        series_name=None,
    ) == ([work], 1)
    repository.list_works.assert_called_with(
        offset=10,
        limit=10,
        query="book",
        media_type="book",
        status="active",
        series_name=None,
    )
    repository.list_series.return_value = (["series"], 1)
    assert service.list_series(page=2, page_size=5, status="active") == (["series"], 1)
    repository.list_series.assert_called_with(status="active", offset=5, limit=5)

    repository.get_work.return_value = work
    repository.list_editions.return_value = [edition]
    assert service.get_work(work_id) == (work, [edition])
    repository.list_files.return_value = ["file"]
    repository.list_volumes.return_value = ["volume"]
    detailed_work, edition_details = service.get_work_detail(work_id)
    assert detailed_work is work
    assert edition_details[0].edition is edition
    assert edition_details[0].files == ("file",)
    assert edition_details[0].volumes == ("volume",)
    repository.get_work.return_value = None
    with pytest.raises(CatalogNotFound):
        service.get_work(work_id)
    with pytest.raises(CatalogNotFound):
        service.get_work_detail(work_id)

    repository.add_work.return_value = work
    assert (
        service.create_work(
            title="  Book   title ",
            author="Author",
            media_type="book",
            metadata={"source": "test"},
        )
        is work
    )
    repository.update_work.return_value = work
    assert (
        service.update_work(
            work_id,
            title=" Updated ",
            author="Author",
            summary="Summary",
            status="active",
        )
        is work
    )
    repository.update_work.return_value = None
    with pytest.raises(CatalogNotFound):
        service.update_work(
            work_id,
            title=None,
            author=None,
            summary=None,
            status=None,
        )

    repository.get_edition.return_value = edition
    repository.list_files.return_value = ["file"]
    assert service.list_files(edition_id) == ["file"]
    repository.get_edition.return_value = None
    with pytest.raises(CatalogNotFound):
        service.list_files(edition_id)
    repository.get_file.return_value = "file"
    assert service.get_file(uuid.uuid4()) == "file"
    repository.get_file.return_value = None
    with pytest.raises(CatalogNotFound):
        service.get_file(uuid.uuid4())

    repository.get_work.return_value = work
    cover_resource = SimpleNamespace(path="/covers/book.webp")
    covers.open.return_value = cover_resource
    assert service.cover(work_id, size="small") is cover_resource
    covers.open.side_effect = FileNotFoundError
    with pytest.raises(CatalogNotFound):
        service.cover(work_id, size="large")
    covers.open.side_effect = None
    repository.get_work.return_value = None
    with pytest.raises(CatalogNotFound):
        service.cover(work_id, size="medium")

    repository.get_work.return_value = work
    repository.set_cover_key.return_value = work
    covers.store.return_value = f"{work_id}/cover.webp"
    assert service.upload_cover(work_id, BytesIO(b"image")) is work
    repository.set_cover_key.return_value = None
    with pytest.raises(CatalogNotFound):
        service.upload_cover(work_id, BytesIO(b"image"))
    covers.delete.assert_called_with(f"{work_id}/cover.webp")
    repository.get_work.return_value = None
    with pytest.raises(CatalogNotFound):
        service.upload_cover(work_id, BytesIO(b"image"))

    repository.update_edition.return_value = edition
    assert (
        service.update_edition(
            work_id,
            edition_id,
            title="  Revised Edition ",
            language="en-US",
            metadata={"publisher": "Shuku"},
        )
        is edition
    )
    repository.update_edition.assert_called_with(
        work_id,
        edition_id,
        title="Revised Edition",
        language="en-US",
        metadata={"publisher": "Shuku"},
    )
    with pytest.raises(ValueError, match="edition title"):
        service.update_edition(
            work_id,
            edition_id,
            title=" ",
            language=None,
            metadata=None,
        )
    repository.update_edition.return_value = None
    with pytest.raises(CatalogNotFound):
        service.update_edition(
            work_id,
            edition_id,
            title=None,
            language=None,
            metadata=None,
        )

    repository.set_primary_edition.return_value = True
    service.set_primary_edition(work_id, edition_id)
    repository.set_primary_edition.return_value = False
    with pytest.raises(CatalogNotFound):
        service.set_primary_edition(work_id, edition_id)

    new_work_id = uuid.uuid4()
    repository.split_edition.return_value = new_work_id
    assert (
        service.split_edition(
            work_id,
            edition_id,
            title="  Independent Work ",
            author="Author",
            copy_shelves=True,
        )
        == new_work_id
    )
    with pytest.raises(ValueError, match="work title"):
        service.split_edition(
            work_id,
            edition_id,
            title=" ",
            author=None,
            copy_shelves=False,
        )
    repository.split_edition.return_value = None
    with pytest.raises(CatalogNotFound):
        service.split_edition(
            work_id,
            edition_id,
            title="Independent Work",
            author=None,
            copy_shelves=False,
        )

    volume_id = uuid.uuid4()
    repository.move_volume.return_value = True
    service.move_volume(work_id, volume_id, direction="up")
    repository.move_volume.return_value = False
    with pytest.raises(CatalogNotFound):
        service.move_volume(work_id, volume_id, direction="down")
    repository.move_volume_to.return_value = True
    service.move_volume_to(
        work_id,
        volume_id,
        target_edition_id=edition_id,
    )
    repository.move_volume_to.return_value = False
    with pytest.raises(CatalogNotFound):
        service.move_volume_to(
            work_id,
            volume_id,
            target_edition_id=edition_id,
        )

    imported = CatalogImport(
        title="Imported",
        author=None,
        media_type="book",
        format="txt",
        source_path="/monitor/imported.txt",
        original_name="imported.txt",
        size_bytes=10,
        checksum="a" * 64,
        metadata={},
    )
    repository.import_file.return_value = edition
    assert service.import_file(imported) is edition
    repository.apply_metadata.return_value = work
    assert service.apply_metadata(work_id, {"title": "Metadata"}) is work
    repository.apply_metadata.return_value = None
    with pytest.raises(CatalogNotFound):
        service.apply_metadata(work_id, {})

    repository.list_shelves.return_value = [shelf]
    assert service.list_shelves(owner_id) == [shelf]
    repository.add_shelf.return_value = shelf
    repository.replace_shelf_items.return_value = True
    assert (
        service.create_shelf(
            owner_id=owner_id,
            name=" My Shelf ",
            description=None,
            kind="manual",
            rules={},
            pinned=True,
            book_ids=[work_id],
        )
        is shelf
    )
    with pytest.raises(ValueError):
        service.create_shelf(
            owner_id=owner_id,
            name=" ",
            description=None,
            kind="manual",
            rules={},
            pinned=False,
            book_ids=[],
        )
    repository.replace_shelf_items.return_value = False
    with pytest.raises(CatalogNotFound):
        service.create_shelf(
            owner_id=owner_id,
            name="Shelf",
            description=None,
            kind="manual",
            rules={},
            pinned=False,
            book_ids=[work_id],
        )

    repository.update_shelf.return_value = shelf
    repository.replace_shelf_items.return_value = True
    assert (
        service.update_shelf(
            shelf_id,
            owner_id,
            name="Renamed",
            description="Description",
            rules={},
            pinned=False,
            book_ids=[work_id],
        )
        is shelf
    )
    repository.update_shelf.return_value = None
    with pytest.raises(CatalogNotFound):
        service.update_shelf(
            shelf_id,
            owner_id,
            name=None,
            description=None,
            rules=None,
            pinned=None,
            book_ids=None,
        )
    repository.update_shelf.return_value = shelf
    repository.replace_shelf_items.return_value = False
    with pytest.raises(CatalogNotFound):
        service.update_shelf(
            shelf_id,
            owner_id,
            name=None,
            description=None,
            rules=None,
            pinned=None,
            book_ids=[work_id],
        )

    repository.get_shelf.return_value = shelf
    repository.list_shelf_works.return_value = ([work], [work_id], 1)
    assert service.get_shelf(shelf_id, owner_id, page=1, page_size=24) == (
        shelf,
        [work],
        [work_id],
        1,
    )
    repository.list_shelf_works.return_value = None
    with pytest.raises(CatalogNotFound):
        service.get_shelf(shelf_id, owner_id, page=1, page_size=24)

    repository.delete_shelf.return_value = True
    service.delete_shelf(shelf_id, owner_id)
    repository.delete_shelf.return_value = False
    with pytest.raises(CatalogNotFound):
        service.delete_shelf(shelf_id, owner_id)
    repository.add_shelf_item.return_value = True
    service.set_shelf_item(shelf_id, owner_id, work_id, present=True)
    repository.remove_shelf_item.return_value = True
    service.set_shelf_item(shelf_id, owner_id, work_id, present=False)
    repository.remove_shelf_item.return_value = False
    with pytest.raises(CatalogNotFound):
        service.set_shelf_item(shelf_id, owner_id, work_id, present=False)

    repository.category_facets.return_value = {"tags": []}
    assert service.facets() == {"tags": []}
    repository.list_categories.return_value = ([category], 1)
    assert service.list_categories(kind="tag", query=None, page=1, page_size=10) == (
        [category],
        1,
    )
    repository.rename_category.return_value = category
    assert service.rename_category(category_id, " New ") is category
    with pytest.raises(ValueError):
        service.rename_category(category_id, " ")
    repository.rename_category.return_value = None
    with pytest.raises(CatalogNotFound):
        service.rename_category(category_id, "missing")
    repository.merge_categories.return_value = category
    assert (
        service.merge_categories(
            kind="tag",
            target_id=category_id,
            source_ids=[uuid.uuid4()],
        )
        is category
    )
    with pytest.raises(ValueError):
        service.merge_categories(
            kind="tag",
            target_id=category_id,
            source_ids=[category_id],
        )
    repository.merge_categories.return_value = None
    with pytest.raises(CatalogNotFound):
        service.merge_categories(
            kind="tag",
            target_id=category_id,
            source_ids=[uuid.uuid4()],
        )
    repository.delete_category.return_value = True
    service.delete_category(category_id)
    repository.delete_category.return_value = False
    with pytest.raises(CatalogNotFound):
        service.delete_category(category_id)
    assert unit.commits >= 10


def test_ingestion_service_complete_success_and_failure_surface() -> None:
    unit = FakeUnitOfWork("ingestion")
    repository = unit.ingestion
    discovery = MagicMock()
    uploads = MagicMock()
    service = IngestionService(
        uow_factory=lambda: unit,
        discovery=discovery,
        uploads=uploads,
    )
    actor = uuid.uuid4()
    job_id = uuid.uuid4()
    folder_id = uuid.uuid4()
    job = SimpleNamespace(id=job_id)
    folder = SimpleNamespace(
        id=folder_id,
        path="/monitor/books",
        enabled=True,
        recursive=True,
        move_source=False,
    )
    result = SimpleNamespace(job_id=job_id)

    repository.list_jobs.return_value = ([job], 1)
    assert service.list_jobs(page=2, page_size=5, status="queued") == ([job], 1)
    repository.enqueue.return_value = result
    assert (
        service.enqueue(
            source_path="/monitor/book.epub",
            requested_by=actor,
            idempotency_key=None,
        )
        is result
    )
    uploads.store.return_value = "/storage/upload.epub"
    assert (
        service.upload(
            name="upload.epub",
            stream=BytesIO(b"book"),
            requested_by=actor,
            idempotency_key="upload-key",
        )
        is result
    )

    for method_name in ("retry", "cancel", "delete_job"):
        method = getattr(service, method_name)
        repository_method = getattr(repository, method_name.replace("delete_job", "delete_job"))
        repository_method.return_value = True
        method(job_id)
        repository_method.return_value = False
        with pytest.raises(IngestionNotFound):
            method(job_id)
    repository.clear_finished.return_value = 3
    assert service.clear_finished() == 3

    repository.list_folders.return_value = [folder]
    assert service.list_folders() == [folder]
    discovery.tree.return_value = ("tree", "/monitor")
    assert service.directory_tree("/monitor") == ("tree", "/monitor")
    discovery.validate_folder.return_value = "/monitor/books"
    repository.add_folder.return_value = folder
    assert (
        service.add_folder(
            path="/monitor/books",
            recursive=True,
            move_source=False,
            options={},
        )
        is folder
    )
    repository.update_folder.return_value = folder
    assert (
        service.update_folder(
            folder_id,
            enabled=False,
            recursive=None,
            move_source=None,
            options=None,
        )
        is folder
    )
    repository.update_folder.return_value = None
    with pytest.raises(IngestionNotFound):
        service.update_folder(
            folder_id,
            enabled=None,
            recursive=None,
            move_source=None,
            options=None,
        )
    repository.delete_folder.return_value = True
    service.delete_folder(folder_id)
    repository.delete_folder.return_value = False
    with pytest.raises(IngestionNotFound):
        service.delete_folder(folder_id)

    repository.get_folder.return_value = folder
    repository.update_folder.return_value = folder
    discovery.discover.return_value = ["/monitor/books/one.epub", "/monitor/books/two.pdf"]
    scanned = service.scan_folder(folder_id, actor)
    assert scanned == [result, result]
    repository.get_folder.return_value = None
    with pytest.raises(IngestionNotFound):
        service.scan_folder(folder_id, actor)
    repository.list_folders.return_value = [
        folder,
        SimpleNamespace(id=uuid.uuid4(), enabled=False),
    ]
    repository.get_folder.return_value = folder
    assert len(service.scan_all_folders(actor)) == 2
    assert len(service.scan_directory("/monitor/books", actor)) == 2


def test_metadata_discovery_and_delivery_services() -> None:
    metadata_uow = FakeUnitOfWork("metadata")
    metadata_repo = metadata_uow.metadata
    catalog = MagicMock()
    metadata = MetadataService(uow_factory=lambda: metadata_uow, catalog=catalog)
    provider_id = uuid.uuid4()
    work_id = uuid.uuid4()
    job_id = uuid.uuid4()
    provider = SimpleNamespace(id=provider_id)
    job = SimpleNamespace(id=job_id)
    candidate = MetadataCandidate(
        provider_id=provider_id,
        external_id="external",
        title="Candidate",
        author="Author",
        cover_url="https://example.com/cover.jpg",
        confidence=0.9,
        raw_payload={"source": "test"},
    )
    metadata_repo.list_providers.return_value = [provider]
    assert metadata.list_providers() == [provider]
    metadata_repo.add_provider.return_value = provider
    assert (
        metadata.add_provider(
            slug="provider",
            name="Provider",
            enabled=True,
            priority=1,
            config={},
        )
        is provider
    )
    metadata_repo.update_provider.return_value = provider
    assert (
        metadata.update_provider(
            provider_id,
            name="Updated",
            enabled=False,
            priority=2,
            config={},
        )
        is provider
    )
    metadata_repo.update_provider.return_value = None
    with pytest.raises(MetadataNotFound):
        metadata.update_provider(
            provider_id,
            name=None,
            enabled=None,
            priority=None,
            config=None,
        )
    metadata_repo.enqueue_job.return_value = job
    assert (
        metadata.enqueue(
            work_id=work_id,
            requested_by=uuid.uuid4(),
            query="book",
            idempotency_key=None,
        )
        is job
    )
    metadata_repo.list_jobs.return_value = ([job], 1)
    assert metadata.list_jobs(page=1, page_size=10, status=None) == ([job], 1)
    metadata_repo.get_job.return_value = job
    metadata_repo.list_candidates.return_value = [candidate]
    assert metadata.list_candidates(job_id) == [candidate]
    metadata_repo.get_job.return_value = None
    with pytest.raises(MetadataNotFound):
        metadata.list_candidates(job_id)
    catalog.apply_metadata.return_value = object()
    metadata.apply_candidate(
        work_id=work_id,
        candidate=candidate,
        patch=MetadataPatch(
            title="Patched",
            author=None,
            series="Series",
            summary="Summary",
            cover_url=None,
            extra={"language": "zh-CN"},
        ),
    )
    catalog.apply_metadata.return_value = None
    with pytest.raises(MetadataNotFound):
        metadata.apply_candidate(
            work_id=work_id,
            candidate=candidate,
            patch=MetadataPatch(),
        )

    discovery_uow = FakeUnitOfWork("discovery")
    discovery_repo = discovery_uow.discovery
    search_port = MagicMock()
    discovery = DiscoveryService(
        uow_factory=lambda: discovery_uow,
        search_port=search_port,
    )
    source_id = uuid.uuid4()
    result_id = uuid.uuid4()
    source = SimpleNamespace(
        id=source_id,
        name="Source",
        base_url="https://example.com",
        enabled=True,
    )
    result = SimpleNamespace(id=result_id, source_id=source_id)
    download = SimpleNamespace(id=uuid.uuid4())
    discovery_repo.list_sources.return_value = [source]
    assert discovery.list_sources() == [source]
    discovery_repo.add_source.return_value = source
    assert (
        discovery.add_source(
            name="Source",
            kind="json-http",
            base_url="https://example.com/",
            enabled=True,
            config={},
        )
        is source
    )
    discovery_repo.update_source.return_value = source
    assert (
        discovery.update_source(
            source_id,
            name="Updated",
            base_url="https://example.org/",
            enabled=False,
            config={},
        )
        is source
    )
    discovery_repo.update_source.return_value = None
    with pytest.raises(DiscoveryNotFound):
        discovery.update_source(
            source_id,
            name=None,
            base_url=None,
            enabled=None,
            config=None,
        )
    discovery_repo.delete_source.return_value = True
    discovery.delete_source(source_id)
    discovery_repo.delete_source.return_value = False
    with pytest.raises(DiscoveryNotFound):
        discovery.delete_source(source_id)
    discovery_repo.get_source.return_value = source
    search_port.search.return_value = ["found"]
    discovery_repo.save_results.return_value = [result]
    assert discovery.search(source_id, "query") == [result]
    discovery_repo.get_source.return_value = None
    with pytest.raises(DiscoveryNotFound):
        discovery.search(source_id, "query")
    discovery_repo.list_results.return_value = ([result], 1)
    assert discovery.list_results(page=1, page_size=10, state=None) == ([result], 1)
    discovery_repo.get_result.return_value = result
    discovery_repo.enqueue_download.return_value = download
    assert (
        discovery.enqueue_download(
            result_id=result_id,
            requested_by=uuid.uuid4(),
            idempotency_key=None,
        )
        is download
    )
    discovery_repo.get_result.return_value = None
    with pytest.raises(DiscoveryNotFound):
        discovery.enqueue_download(
            result_id=result_id,
            requested_by=uuid.uuid4(),
            idempotency_key=None,
        )
    discovery_repo.list_downloads.return_value = ([download], 1)
    assert discovery.list_downloads(page=1, page_size=10, status="queued") == ([download], 1)

    delivery_uow = FakeUnitOfWork("delivery")
    delivery_repo = delivery_uow.delivery
    files = MagicMock()
    smtp = MagicMock()
    delivery = DeliveryService(
        uow_factory=lambda: delivery_uow,
        files=files,
        smtp=smtp,
    )
    owner_id = uuid.uuid4()
    file_id = uuid.uuid4()
    email_settings = SimpleNamespace(host="smtp.example.com")
    kindle_settings = SimpleNamespace(kindle_email="reader@kindle.com")
    delivery_job = SimpleNamespace(id=uuid.uuid4())
    delivery_repo.get_email_settings.return_value = email_settings
    assert delivery.get_email_settings(owner_id) is email_settings
    delivery_repo.save_email_settings.return_value = email_settings
    assert (
        delivery.save_email_settings(
            owner_id=owner_id,
            host="smtp.example.com",
            port=587,
            username=None,
            password=None,
            clear_password=False,
            sender="sender@example.com",
            security="starttls",
        )
        is email_settings
    )
    with pytest.raises(ValueError):
        delivery.save_email_settings(
            owner_id=owner_id,
            host="smtp.example.com",
            port=587,
            username=None,
            password=None,
            clear_password=False,
            sender="sender@example.com",
            security="invalid",
        )
    delivery_repo.smtp_configuration.return_value = email_settings
    email_settings.sender = "sender@example.com"
    assert delivery.email_status(owner_id) == (True, "sender@example.com")
    delivery.test_email(owner_id, "recipient@example.com")
    delivery_repo.smtp_configuration.return_value = None
    assert delivery.email_status(owner_id) == (False, None)
    with pytest.raises(DeliveryNotFound):
        delivery.test_email(owner_id, "recipient@example.com")
    delivery_repo.get_kindle_settings.return_value = kindle_settings
    assert delivery.get_kindle_settings(owner_id) is kindle_settings
    delivery_repo.save_kindle_settings.return_value = kindle_settings
    assert (
        delivery.save_kindle_settings(
            owner_id=owner_id,
            kindle_email="reader@kindle.com",
            convert_before_send=False,
            options={},
        )
        is kindle_settings
    )
    files.get_deliverable.return_value = SimpleNamespace(id=file_id)
    delivery_repo.get_kindle_settings.return_value = kindle_settings
    delivery_repo.enqueue.return_value = delivery_job
    assert (
        delivery.enqueue_kindle(
            owner_id=owner_id,
            file_id=file_id,
            subject="Book",
            idempotency_key=None,
        )
        is delivery_job
    )
    files.get_deliverable.return_value = None
    with pytest.raises(DeliveryNotFound):
        delivery.enqueue_kindle(
            owner_id=owner_id,
            file_id=file_id,
            subject="Book",
            idempotency_key=None,
        )
    files.get_deliverable.return_value = SimpleNamespace(id=file_id)
    delivery_repo.get_kindle_settings.return_value = None
    with pytest.raises(DeliveryNotFound):
        delivery.enqueue_kindle(
            owner_id=owner_id,
            file_id=file_id,
            subject="Book",
            idempotency_key=None,
        )
    delivery_repo.list_jobs.return_value = ([delivery_job], 1)
    assert delivery.list_jobs(
        owner_id=owner_id,
        page=1,
        page_size=10,
        status=None,
    ) == ([delivery_job], 1)
    delivery_repo.cancel.return_value = True
    delivery.cancel(delivery_job.id, owner_id)
    delivery_repo.cancel.return_value = False
    with pytest.raises(DeliveryNotFound):
        delivery.cancel(delivery_job.id, owner_id)
    delivery_repo.retry.return_value = delivery_job
    assert delivery.retry(delivery_job.id, owner_id) is delivery_job
    delivery_repo.retry.return_value = None
    with pytest.raises(DeliveryNotFound):
        delivery.retry(delivery_job.id, owner_id)


def test_operations_and_reading_services() -> None:
    operations_uow = FakeUnitOfWork("operations")
    operations_repo = operations_uow.operations
    healthy = MagicMock()
    healthy.check.return_value = SimpleNamespace(name="database", status="healthy")
    backup_executor = MagicMock()
    restore_control = MagicMock()
    operations = OperationsService(
        uow_factory=lambda: operations_uow,
        health_contributors=(healthy,),
        backup_executor=backup_executor,
        restore_control=restore_control,
        app_version="0.4.0",
        alembic_revision="0001",
    )
    actor = uuid.uuid4()
    backup_id = uuid.uuid4()
    backup = SimpleNamespace(id=backup_id)
    assert operations.health()[0].status == "healthy"
    operations_repo.list_settings.return_value = ["setting"]
    assert operations.list_settings() == ["setting"]
    operations_repo.save_settings.return_value = ["saved"]
    assert operations.save_settings({"key": {"value": "on"}}, actor) == ["saved"]
    operations_repo.list_events.return_value = (["event"], 1)
    assert operations.list_events(page=1, page_size=10, kind=None) == (["event"], 1)
    operations_repo.request_backup.return_value = backup
    assert operations.request_backup(actor) is backup
    operations_repo.list_backups.return_value = [backup]
    assert operations.list_backups() == [backup]
    operations_repo.get_backup.return_value = backup
    assert operations.get_backup(backup_id) is backup
    operations_repo.get_backup.return_value = None
    with pytest.raises(OperationsNotFound):
        operations.get_backup(backup_id)
    operations_repo.delete_backup.return_value = backup
    operations.delete_backup(backup_id)
    operations_repo.delete_backup.return_value = None
    with pytest.raises(OperationsNotFound):
        operations.delete_backup(backup_id)
    operations_repo.get_backup.return_value = backup
    archive = SimpleNamespace(path="/backup.dump")
    backup_executor.open.return_value = archive
    assert operations.download_backup(backup_id) is archive
    backup_executor.open.side_effect = FileNotFoundError
    with pytest.raises(OperationsNotFound):
        operations.download_backup(backup_id)
    backup_executor.open.side_effect = None
    operations_repo.mark_restoring.return_value = backup
    restore_control.request.return_value = "restore-request"
    assert operations.request_restore(backup_id, actor) == "restore-request"
    operations_repo.mark_restoring.return_value = None
    with pytest.raises(OperationsNotFound):
        operations.request_restore(backup_id, actor)

    reading_uow = FakeUnitOfWork("reading")
    reading_repo = reading_uow.reading
    catalog = MagicMock()
    resources = MagicMock()
    reading = ReadingService(
        uow_factory=lambda: reading_uow,
        catalog=catalog,
        resources=resources,
    )
    work_id = uuid.uuid4()
    edition_id = uuid.uuid4()
    file_id = uuid.uuid4()
    user_id = uuid.uuid4()
    bookmark_id = uuid.uuid4()
    work = SimpleNamespace(id=work_id, title="Book", author="Author")
    edition = SimpleNamespace(id=edition_id, work_id=work_id, title="Edition", format="epub")
    file = SimpleNamespace(
        id=file_id,
        media_type="application/epub+zip",
        checksum="a" * 64,
    )
    catalog.get_edition.return_value = edition
    catalog.get_work.return_value = work
    catalog.files_for_edition.return_value = [file]
    catalog.volumes_for_edition.return_value = []
    reading_repo.get_progress.return_value = None
    reading_repo.list_bookmarks.return_value = []
    reading_repo.get_preference.return_value = None
    target, progress, bookmarks, preference, files, volumes = reading.bootstrap(
        user_id=user_id,
        edition_id=edition_id,
    )
    assert target.file_id == file_id
    assert (progress, bookmarks, preference) == (None, [], None)
    assert files == [file]
    assert volumes == []
    catalog.get_edition.return_value = None
    with pytest.raises(ReadingNotFound):
        reading.bootstrap(user_id=user_id, edition_id=edition_id)
    catalog.get_edition.return_value = edition
    catalog.get_work.return_value = None
    with pytest.raises(ReadingNotFound):
        reading.bootstrap(user_id=user_id, edition_id=edition_id)
    catalog.get_work.return_value = work
    catalog.files_for_edition.return_value = []
    with pytest.raises(ReadingNotFound):
        reading.bootstrap(user_id=user_id, edition_id=edition_id)
    catalog.files_for_edition.return_value = [file]

    stream = SimpleNamespace(total_size=10)
    resources.open.return_value = stream
    assert (
        reading.resource(
            user_id=user_id,
            edition_id=edition_id,
            requested_range=None,
        )
        is stream
    )
    resources.open.side_effect = FileNotFoundError
    with pytest.raises(ReadingNotFound):
        reading.resource(user_id=user_id, edition_id=edition_id, requested_range=None)
    resources.open.side_effect = None
    catalog.get_file.return_value = file
    assert (
        reading.file_resource(
            user_id=user_id,
            file_id=file_id,
            requested_range=None,
        )
        is stream
    )
    catalog.get_file.return_value = None
    with pytest.raises(ReadingNotFound):
        reading.file_resource(
            user_id=user_id,
            file_id=file_id,
            requested_range=None,
        )
    catalog.get_file.return_value = file
    pages = [SimpleNamespace(index=0)]
    resources.comic_pages.return_value = pages
    assert reading.comic_pages(target_id=edition_id) == pages
    resources.comic_pages.side_effect = ValueError
    with pytest.raises(ReadingNotFound):
        reading.comic_pages(target_id=edition_id)
    resources.comic_pages.side_effect = None
    resources.open_comic_page.return_value = stream
    assert (
        reading.comic_page(
            user_id=user_id,
            target_id=edition_id,
            page_index=0,
        )
        is stream
    )
    resources.open_comic_page.side_effect = FileNotFoundError
    with pytest.raises(ReadingNotFound):
        reading.comic_page(user_id=user_id, target_id=edition_id, page_index=0)
    resources.open_comic_page.side_effect = None

    assert reading.get_progress(user_id=user_id, edition_id=edition_id) is None
    saved_progress = SimpleNamespace(version=1)
    reading_repo.save_progress.return_value = saved_progress
    assert (
        reading.save_progress(
            user_id=user_id,
            edition_id=edition_id,
            device_id="browser",
            position={"page": 1},
            percentage=0.5,
            occurred_at=None,
            expected_version=None,
        )
        is saved_progress
    )
    reading_repo.save_progress.side_effect = ValueError
    with pytest.raises(ProgressConflict):
        reading.save_progress(
            user_id=user_id,
            edition_id=edition_id,
            device_id="browser",
            position={},
            percentage=0.5,
            occurred_at=datetime.now(UTC),
            expected_version=2,
        )
    reading_repo.save_progress.side_effect = None
    assert reading.list_bookmarks(user_id=user_id, edition_id=edition_id) == []
    bookmark = SimpleNamespace(id=bookmark_id)
    reading_repo.put_bookmark.return_value = bookmark
    assert (
        reading.put_bookmark(
            user_id=user_id,
            edition_id=edition_id,
            client_id="bookmark",
            label="Label",
            position={},
            excerpt=None,
        )
        is bookmark
    )
    reading_repo.delete_bookmark.return_value = True
    reading.delete_bookmark(
        user_id=user_id,
        edition_id=edition_id,
        bookmark_id=bookmark_id,
    )
    reading_repo.delete_bookmark.return_value = False
    with pytest.raises(ReadingNotFound):
        reading.delete_bookmark(
            user_id=user_id,
            edition_id=edition_id,
            bookmark_id=bookmark_id,
        )
    assert reading.get_preference(user_id=user_id, scope="edition", target_id=edition_id) is None
    saved_preference = SimpleNamespace(values={"theme": "night"})
    reading_repo.save_preference.return_value = saved_preference
    assert (
        reading.save_preference(
            user_id=user_id,
            scope="edition",
            target_id=edition_id,
            values={"theme": "night"},
        )
        is saved_preference
    )

    now = datetime.now(UTC)
    opaque_token = uuid.uuid4().hex
    reading_repo.claim_locations.return_value = SimpleNamespace(
        serialized="locations",
        token_hash=opaque_token,
        expires_at=now + timedelta(minutes=1),
    )
    assert (
        reading.claim_epub_locations(
            user_id=user_id,
            edition_id=edition_id,
            content_fingerprint="fingerprint",
            cache_version=1,
            break_size=1024,
        ).status
        == "ready"
    )
    reading_repo.claim_locations.return_value = SimpleNamespace(
        serialized=None,
        token_hash=opaque_token,
        expires_at=now + timedelta(minutes=1),
    )
    assert (
        reading.claim_epub_locations(
            user_id=user_id,
            edition_id=edition_id,
            content_fingerprint="fingerprint",
            cache_version=1,
            break_size=1024,
        ).status
        == "generating"
    )
    reading_repo.save_locations.return_value = SimpleNamespace(serialized="locations")
    assert (
        reading.save_epub_locations(
            edition_id=edition_id,
            content_fingerprint="fingerprint",
            cache_version=1,
            break_size=1024,
            lease_token=opaque_token,
            serialized="locations",
        ).status
        == "ready"
    )
    reading_repo.save_locations.side_effect = ValueError
    with pytest.raises(LocationClaimConflict):
        reading.save_epub_locations(
            edition_id=edition_id,
            content_fingerprint="fingerprint",
            cache_version=1,
            break_size=1024,
            lease_token=opaque_token,
            serialized="locations",
        )
