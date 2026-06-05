"""SQLite persistence layer for the Prescription finite state machine.

Uses SQLAlchemy to serialise the FSM state and the audit history to a
relational table. The Prescription class itself does not depend on this
module; persistence is implemented as a repository that converts between
ORM rows and live Prescription instances. This separation keeps the FSM
core free of database concerns and preserves its deterministic behaviour.

The history list is serialised as a JSON string in a single column so
that the schema stays simple and portable across SQLite installations.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional, Tuple

from sqlalchemy import Column, DateTime, Integer, String, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool

from .prescription import Prescription, STATES


Base = declarative_base()


class PrescriptionRecord(Base):
    """Relational row that stores the persisted state of one prescription."""

    __tablename__ = "prescriptions"

    id = Column(Integer, primary_key=True)
    identifier = Column(String, unique=True, nullable=False, index=True)
    state = Column(String, nullable=False)
    history = Column(String, nullable=False, default="[]")
    created_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


def create_engine_and_session(
    url: str = "sqlite:///:memory:",
    shared_memory: bool = False,
) -> Tuple[object, sessionmaker]:
    """Build a SQLAlchemy engine and session factory.

    When the database URL is the in-memory SQLite default, callers can
    set shared_memory=True to pin a single connection via StaticPool so
    that multiple sessions see the same database. This is useful for
    tests that simulate a restart against an in-memory backing store.
    """
    if shared_memory and url.startswith("sqlite:///:memory:"):
        engine = create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            future=True,
        )
    else:
        engine = create_engine(url, future=True)

    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, future=True)
    return engine, session_factory


class PrescriptionRepository:
    """Reads and writes Prescription state to a relational backing store.

    The repository is a thin wrapper around a SQLAlchemy session. It does
    not own the session lifecycle; callers are responsible for opening
    and closing sessions in the usual SQLAlchemy fashion. This keeps the
    persistence layer composable with whatever transaction strategy the
    surrounding application prefers.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, prescription: Prescription) -> None:
        """Insert a new record or update an existing one in place.

        The prescription identifier acts as the natural key. Calling save
        for the same identifier multiple times updates the existing row
        rather than creating a duplicate.
        """
        if prescription.identifier is None:
            raise ValueError(
                "Prescription must have an identifier before it can be persisted."
            )

        record = (
            self.session.query(PrescriptionRecord)
            .filter_by(identifier=prescription.identifier)
            .one_or_none()
        )

        history_json = json.dumps(prescription.history)
        now = datetime.now(timezone.utc)

        if record is None:
            record = PrescriptionRecord(
                identifier=prescription.identifier,
                state=prescription.state,
                history=history_json,
                created_at=now,
                updated_at=now,
            )
            self.session.add(record)
        else:
            record.state = prescription.state
            record.history = history_json
            record.updated_at = now

        self.session.commit()

    def load(self, identifier: str) -> Optional[Prescription]:
        """Return a fully reconstructed Prescription, or None if absent.

        The reconstruction sets the FSM directly to the persisted state
        and restores the audit history list. The loaded instance can be
        used exactly like a fresh instance for subsequent transitions.
        """
        record = (
            self.session.query(PrescriptionRecord)
            .filter_by(identifier=identifier)
            .one_or_none()
        )
        if record is None:
            return None

        if record.state not in STATES:
            raise ValueError(
                f"Persisted state '{record.state}' is not in the FSM state set."
            )

        prescription = Prescription(identifier=record.identifier)
        prescription.machine.set_state(record.state)
        prescription.history = json.loads(record.history)
        return prescription
