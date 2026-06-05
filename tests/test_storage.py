"""Tests for the SQLAlchemy persistence layer."""

import os
import tempfile

import pytest

from src.prescription import Prescription
from src.storage import PrescriptionRepository, create_engine_and_session


@pytest.fixture
def session():
    _, session_factory = create_engine_and_session(
        "sqlite:///:memory:", shared_memory=True
    )
    sess = session_factory()
    yield sess
    sess.close()


class TestSaveAndLoad:
    def test_save_then_load_returns_equivalent_prescription(self, session):
        prescription = Prescription(identifier="rx-001")
        prescription.trigger_event("sign")
        repo = PrescriptionRepository(session)
        repo.save(prescription)

        loaded = repo.load("rx-001")
        assert loaded is not None
        assert loaded.identifier == "rx-001"
        assert loaded.state == "signed"
        assert loaded.history == ["signed"]

    def test_load_unknown_identifier_returns_none(self, session):
        repo = PrescriptionRepository(session)
        assert repo.load("missing") is None

    def test_round_trip_preserves_full_history(self, session):
        prescription = Prescription(identifier="rx-002")
        prescription.trigger_event("sign")
        prescription.trigger_event("transmit")
        prescription.trigger_event("dispense")
        repo = PrescriptionRepository(session)
        repo.save(prescription)

        loaded = repo.load("rx-002")
        assert loaded.state == "dispensed"
        assert loaded.history == ["signed", "transmitted", "dispensed"]
        assert loaded.is_terminal is True

    def test_save_updates_existing_record(self, session):
        prescription = Prescription(identifier="rx-003")
        prescription.trigger_event("sign")
        repo = PrescriptionRepository(session)
        repo.save(prescription)

        prescription.trigger_event("transmit")
        repo.save(prescription)

        loaded = repo.load("rx-003")
        assert loaded.state == "transmitted"
        assert loaded.history == ["signed", "transmitted"]

    def test_save_requires_identifier(self, session):
        prescription = Prescription()
        repo = PrescriptionRepository(session)
        with pytest.raises(ValueError):
            repo.save(prescription)

    def test_loaded_prescription_continues_lifecycle(self, session):
        prescription = Prescription(identifier="rx-004")
        prescription.trigger_event("sign")
        repo = PrescriptionRepository(session)
        repo.save(prescription)

        loaded = repo.load("rx-004")
        loaded.trigger_event("transmit")
        loaded.trigger_event("dispense")
        assert loaded.state == "dispensed"


class TestRecoveryAfterRestart:
    def test_recovery_from_file_backed_database(self):
        """Save against one session, dispose of it, then reload via a
        new session against the same file. This simulates a process
        restart against a durable backing store."""
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        url = f"sqlite:///{tmp.name}"
        try:
            _, session_factory = create_engine_and_session(url)

            first = session_factory()
            prescription = Prescription(identifier="rx-restart")
            prescription.trigger_event("sign")
            prescription.trigger_event("transmit")
            PrescriptionRepository(first).save(prescription)
            first.close()

            second = session_factory()
            loaded = PrescriptionRepository(second).load("rx-restart")
            second.close()

            assert loaded is not None
            assert loaded.state == "transmitted"
            assert loaded.history == ["signed", "transmitted"]
        finally:
            os.unlink(tmp.name)
