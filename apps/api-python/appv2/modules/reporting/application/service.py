from __future__ import annotations

from appv2.modules.reporting.contracts import (
    DashboardProjection,
    ManagementProjection,
    ReportingReadPort,
)


class ReportingService:
    def __init__(self, read_port: ReportingReadPort) -> None:
        self._read_port = read_port

    def dashboard(self) -> DashboardProjection:
        return self._read_port.dashboard()

    def management(self) -> ManagementProjection:
        return self._read_port.management()
