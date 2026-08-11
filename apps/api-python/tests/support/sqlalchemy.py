from __future__ import annotations

from dataclasses import dataclass, field
from typing import Self

from sqlalchemy import event
from sqlalchemy.engine import Connection, Engine, ExecutionContext


@dataclass(frozen=True, slots=True)
class StatementObservation:
    is_insert: bool
    is_update: bool
    is_delete: bool
    executemany: bool

    @property
    def is_dml(self) -> bool:
        return self.is_insert or self.is_update or self.is_delete


@dataclass
class StatementRecorder:
    """Count SQLAlchemy executions without inspecting rendered SQL text."""

    engine: Engine
    observations: list[StatementObservation] = field(default_factory=list)
    _attached: bool = field(default=False, init=False)

    def _capture(
        self,
        connection: Connection,
        cursor: object,
        statement: str,
        parameters: object,
        context: ExecutionContext,
        executemany: bool,
    ) -> None:
        del connection, cursor, statement, parameters
        self.observations.append(
            StatementObservation(
                is_insert=bool(context.isinsert),
                is_update=bool(context.isupdate),
                is_delete=bool(context.isdelete),
                executemany=executemany,
            )
        )

    def attach(self) -> None:
        if self._attached:
            return
        event.listen(self.engine, "before_cursor_execute", self._capture)
        self._attached = True

    def reset_after_warmup(self) -> None:
        """Discard schema/reflection warm-up and begin the measured window."""

        self.observations.clear()

    def close(self) -> None:
        if not self._attached:
            return
        event.remove(self.engine, "before_cursor_execute", self._capture)
        self._attached = False

    @property
    def statement_count(self) -> int:
        return len(self.observations)

    @property
    def dml_count(self) -> int:
        return sum(observation.is_dml for observation in self.observations)

    def __enter__(self) -> Self:
        self.attach()
        return self

    def __exit__(self, *unused: object) -> None:
        del unused
        self.close()
