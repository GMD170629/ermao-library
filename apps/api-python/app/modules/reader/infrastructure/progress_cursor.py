from __future__ import annotations

from sqlalchemy.orm import Session

from app.modules.reader.application.progress import ClaimClientSequenceCommand
from app.modules.reader.infrastructure import queries


class SqlAlchemyReaderProgressCursor:
    def __init__(self, session: Session):
        self._session = session

    def claim(self, command: ClaimClientSequenceCommand) -> bool:
        return queries.claim_client_sequence(
            self._session,
            user_id=command.user_id,
            work_id=command.work_id,
            client_id=command.client_id,
            client_sequence=command.client_sequence,
            mutation_id=command.mutation_id,
            now=command.now,
        )
