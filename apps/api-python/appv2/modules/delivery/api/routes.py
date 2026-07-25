import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, status
from pydantic import EmailStr, Field

from appv2.modules.accounts.contracts import AccountView, CurrentAccount
from appv2.modules.delivery.application import DeliveryNotFound, DeliveryService
from appv2.modules.delivery.contracts import DeliveryJob, EmailSettings, KindleSettings
from appv2.platform.http import AppProblem, CamelModel, Page


class EmailSettingsResponse(CamelModel):
    owner_id: uuid.UUID
    host: str
    port: int
    username: str | None
    sender: str
    use_tls: bool
    password_set: bool

    @classmethod
    def from_view(cls, value: EmailSettings) -> "EmailSettingsResponse":
        return cls.model_validate(value)


class EmailSettingsRequest(CamelModel):
    host: str = Field(min_length=1, max_length=500)
    port: int = Field(ge=1, le=65535)
    username: str | None = Field(default=None, max_length=500)
    password: str | None = Field(default=None, max_length=1000)
    sender: EmailStr
    use_tls: bool = True


class EmailTestRequest(CamelModel):
    recipient: EmailStr


class KindleSettingsResponse(CamelModel):
    owner_id: uuid.UUID
    kindle_email: EmailStr
    convert_before_send: bool
    options: dict[str, object]

    @classmethod
    def from_view(cls, value: KindleSettings) -> "KindleSettingsResponse":
        return cls.model_validate(value)


class KindleSettingsRequest(CamelModel):
    kindle_email: EmailStr
    convert_before_send: bool = False
    options: dict[str, object] = Field(default_factory=dict)


class KindleJobRequest(CamelModel):
    file_id: uuid.UUID
    subject: str = Field(min_length=1, max_length=1000)


class DeliveryJobResponse(CamelModel):
    id: uuid.UUID
    file_id: uuid.UUID
    kind: str
    recipient: str
    subject: str
    status: str
    attempt: int
    next_attempt_at: datetime
    error_code: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_view(cls, value: DeliveryJob) -> "DeliveryJobResponse":
        return cls.model_validate(value)


def create_router(service: DeliveryService, current_account: CurrentAccount) -> APIRouter:
    router = APIRouter(prefix="/delivery")
    Actor = Annotated[AccountView, Depends(current_account)]

    def missing(error: DeliveryNotFound) -> AppProblem:
        return AppProblem(
            status=404,
            code="DELIVERY_RESOURCE_NOT_FOUND",
            title="Delivery resource not found",
            message_key="not_found",
        )

    @router.get("/email/settings", response_model=EmailSettingsResponse | None)
    def email_settings(actor: Actor) -> EmailSettingsResponse | None:
        value = service.get_email_settings(actor.id)
        return EmailSettingsResponse.from_view(value) if value else None

    @router.put("/email/settings", response_model=EmailSettingsResponse)
    def save_email_settings(payload: EmailSettingsRequest, actor: Actor) -> EmailSettingsResponse:
        value = service.save_email_settings(
            owner_id=actor.id,
            host=payload.host,
            port=payload.port,
            username=payload.username,
            password=payload.password,
            sender=str(payload.sender),
            use_tls=payload.use_tls,
        )
        return EmailSettingsResponse.from_view(value)

    @router.post("/email/test", status_code=status.HTTP_204_NO_CONTENT)
    def test_email(payload: EmailTestRequest, actor: Actor) -> None:
        try:
            service.test_email(actor.id, str(payload.recipient))
        except DeliveryNotFound as error:
            raise missing(error) from error

    @router.get("/kindle/settings", response_model=KindleSettingsResponse | None)
    def kindle_settings(actor: Actor) -> KindleSettingsResponse | None:
        value = service.get_kindle_settings(actor.id)
        return KindleSettingsResponse.from_view(value) if value else None

    @router.put("/kindle/settings", response_model=KindleSettingsResponse)
    def save_kindle_settings(
        payload: KindleSettingsRequest, actor: Actor
    ) -> KindleSettingsResponse:
        value = service.save_kindle_settings(
            owner_id=actor.id,
            kindle_email=str(payload.kindle_email),
            convert_before_send=payload.convert_before_send,
            options=payload.options,
        )
        return KindleSettingsResponse.from_view(value)

    @router.post(
        "/kindle/jobs",
        response_model=DeliveryJobResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def enqueue(
        payload: KindleJobRequest,
        actor: Actor,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> DeliveryJobResponse:
        try:
            value = service.enqueue_kindle(
                owner_id=actor.id,
                file_id=payload.file_id,
                subject=payload.subject,
                idempotency_key=idempotency_key,
            )
        except DeliveryNotFound as error:
            raise missing(error) from error
        return DeliveryJobResponse.from_view(value)

    @router.get("/kindle/jobs", response_model=Page[DeliveryJobResponse])
    def jobs(
        actor: Actor,
        page: int = 1,
        page_size: Annotated[int, Query(alias="pageSize", ge=1, le=200)] = 24,
        job_status: Annotated[str | None, Query(alias="status")] = None,
    ) -> Page[DeliveryJobResponse]:
        size = min(max(page_size, 1), 200)
        values, total = service.list_jobs(
            owner_id=actor.id,
            page=max(page, 1),
            page_size=size,
            status=job_status,
        )
        return Page(
            items=[DeliveryJobResponse.from_view(value) for value in values],
            page=max(page, 1),
            page_size=size,
            total=total,
        )

    @router.post(
        "/kindle/jobs/{job_id}/retry",
        response_model=DeliveryJobResponse | None,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def retry(job_id: uuid.UUID, actor: Actor) -> None:
        try:
            service.retry(job_id, actor.id)
        except DeliveryNotFound as error:
            raise missing(error) from error

    @router.delete("/kindle/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
    def cancel(job_id: uuid.UUID, actor: Actor) -> None:
        try:
            service.cancel(job_id, actor.id)
        except DeliveryNotFound as error:
            raise missing(error) from error

    return router
