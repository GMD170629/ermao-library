from typing import Annotated

from fastapi import APIRouter, Depends

from appv2.modules.accounts.contracts import AccessScope, AccountView, CurrentAccount
from appv2.modules.reporting.application import ReportingService
from appv2.platform.http import AppProblem, CamelModel


class DashboardResponse(CamelModel):
    work_count: int
    edition_count: int
    active_readers: int
    queued_jobs: int
    recent_items: list[dict[str, object]]


class ManagementResponse(CamelModel):
    users: int
    works: int
    files: int
    queued_imports: int
    queued_downloads: int
    queued_deliveries: int
    failed_jobs: int


def create_router(service: ReportingService, current_account: CurrentAccount) -> APIRouter:
    router = APIRouter(prefix="/reporting")
    Actor = Annotated[AccountView, Depends(current_account)]

    def require(actor: AccountView, scope: AccessScope) -> None:
        if scope not in actor.scopes:
            raise AppProblem(
                status=403,
                code="PERMISSION_DENIED",
                title="Permission denied",
                message_key="permission_denied",
                params={"scope": scope.value},
            )

    @router.get("/dashboard", response_model=DashboardResponse)
    def dashboard(actor: Actor) -> DashboardResponse:
        require(actor, AccessScope.CATALOG_READ)
        projection = service.dashboard()
        return DashboardResponse(
            work_count=projection.work_count,
            edition_count=projection.edition_count,
            active_readers=projection.active_readers,
            queued_jobs=projection.queued_jobs,
            recent_items=list(projection.recent_items),
        )

    @router.get("/management", response_model=ManagementResponse)
    def management(actor: Actor) -> ManagementResponse:
        require(actor, AccessScope.OPERATIONS_READ)
        return ManagementResponse.model_validate(service.management())

    return router
