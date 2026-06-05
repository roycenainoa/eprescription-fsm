"""Demonstration script for the electronic prescription FSM.

Runs through a representative set of scenarios so that a reader can verify
the model behaviour without writing Python interactively. Each scenario
prints the events dispatched, the resulting state, and the audit history
or the rejection reason.

The script also exercises the persistence layer, the background expiry
scheduler, and the FHIR MedicationRequest parser so that every operational
extension of the project is visible in one runnable demonstration.

Usage:
    python demo.py
"""

import os
import tempfile
import time

from src.exceptions import InvalidTransitionError, TerminalStateError
from src.fhir import FHIRParseError, prescription_from_fhir
from src.prescription import Prescription
from src.scheduler import ExpiryScheduler
from src.storage import PrescriptionRepository, create_engine_and_session
from src.validator import validate_sequence


def header(title: str) -> None:
    print()
    print("=" * 60)
    print(title)
    print("=" * 60)


def run_scenario(title: str, events: list[str]) -> None:
    print(f"\n[scenario] {title}")
    print(f"  events: {events}")
    prescription = Prescription(identifier="rx-demo")
    for event in events:
        try:
            new_state = prescription.trigger_event(event)
            print(f"    {event:<10} -> {new_state}")
        except (InvalidTransitionError, TerminalStateError) as exc:
            print(f"    {event:<10} REJECTED ({type(exc).__name__})")
            print(f"               reason: {exc}")
            break
    print(f"  final state: {prescription.state}")
    print(f"  history:     {prescription.history}")
    print(f"  terminal:    {prescription.is_terminal}")


def run_validator_demo(title: str, events: list[str]) -> None:
    print(f"\n[validator] {title}")
    print(f"  events:   {events}")
    result = validate_sequence(events)
    print(f"  accepted: {result.accepted}")
    print(f"  final:    {result.final_state}")
    print(f"  consumed: {result.consumed}")
    if not result.accepted:
        print(f"  rejected: {result.rejected_event}")
        print(f"  reason:   {result.rejection_reason}")


def run_persistence_demo() -> None:
    """Save a prescription to a temporary SQLite database, then reload
    from a fresh session to simulate a process restart."""
    print("\n[persistence] Save then reload from SQLite")
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    try:
        _, session_factory = create_engine_and_session(f"sqlite:///{tmp.name}")
        print(f"  database file: {tmp.name}")

        # First session: build a prescription and save it
        first = session_factory()
        prescription = Prescription(identifier="rx-persist-001")
        prescription.trigger_event("sign")
        prescription.trigger_event("transmit")
        PrescriptionRepository(first).save(prescription)
        print(f"  saved:   id={prescription.identifier} "
              f"state={prescription.state} history={prescription.history}")
        first.close()

        # Fresh session against the same database file
        second = session_factory()
        loaded = PrescriptionRepository(second).load("rx-persist-001")
        print(f"  loaded:  id={loaded.identifier} "
              f"state={loaded.state} history={loaded.history}")

        # Continue the lifecycle on the loaded instance
        loaded.trigger_event("dispense")
        PrescriptionRepository(second).save(loaded)
        print(f"  updated: state={loaded.state} history={loaded.history}")
        second.close()
    finally:
        os.unlink(tmp.name)


def run_scheduler_demo() -> None:
    """Schedule an automatic expiry and observe the timer firing.
    Then show the scheduler being cancelled before it can fire."""
    print("\n[scheduler] Auto-expiry after 0.3 seconds from signed")
    prescription = Prescription(identifier="rx-sched-001")
    prescription.trigger_event("sign")
    print(f"  before: state={prescription.state}")
    scheduler = ExpiryScheduler(prescription, delay_seconds=0.3)
    scheduler.start()
    time.sleep(0.5)
    print(f"  after:  state={prescription.state} history={prescription.history}")

    print("\n[scheduler] Dispense before timer fires (expiry is suppressed)")
    prescription = Prescription(identifier="rx-sched-002")
    prescription.trigger_event("sign")
    prescription.trigger_event("transmit")
    scheduler = ExpiryScheduler(prescription, delay_seconds=0.5)
    scheduler.start()
    prescription.trigger_event("dispense")
    scheduler.cancel()
    time.sleep(0.6)
    print(f"  after:  state={prescription.state} history={prescription.history}")


def run_fhir_demo() -> None:
    """Parse a small set of FHIR MedicationRequest payloads. The first
    three show accepted status mappings; the last two show parse errors
    surfaced through FHIRParseError."""
    samples = [
        ("draft", "rx-fhir-001"),
        ("active", "rx-fhir-002"),
        ("completed", "rx-fhir-003"),
    ]
    for status, identifier in samples:
        payload = {
            "resourceType": "MedicationRequest",
            "id": identifier,
            "status": status,
            "intent": "order",
            "medicationCodeableConcept": {"text": "Amoxicillin 500mg"},
            "subject": {"reference": "Patient/example"},
        }
        prescription = prescription_from_fhir(payload)
        print(f"\n[fhir] status='{status}'")
        print(f"  id:      {prescription.identifier}")
        print(f"  state:   {prescription.state}")
        print(f"  history: {prescription.history}")

    # Rejected payloads
    invalid_samples = [
        {"resourceType": "Observation", "id": "rx-fhir-bad-1", "status": "draft"},
        {
            "resourceType": "MedicationRequest",
            "id": "rx-fhir-bad-2",
            "status": "entered-in-error",
        },
    ]
    for payload in invalid_samples:
        print(f"\n[fhir] invalid payload: "
              f"resourceType={payload.get('resourceType')} "
              f"status={payload.get('status')}")
        try:
            prescription_from_fhir(payload)
        except FHIRParseError as exc:
            print(f"  REJECTED (FHIRParseError)")
            print(f"  reason:   {exc}")


def main() -> None:
    header("Accepted workflows")
    run_scenario(
        "Standard lifecycle (drafted to dispensed)",
        ["sign", "transmit", "dispense"],
    )
    run_scenario(
        "Expiry after signing",
        ["sign", "expire"],
    )
    run_scenario(
        "Expiry after transmission",
        ["sign", "transmit", "expire"],
    )
    run_scenario(
        "Cancellation from drafted",
        ["cancel"],
    )
    run_scenario(
        "Cancellation from transmitted",
        ["sign", "transmit", "cancel"],
    )

    header("Rejected workflows")
    run_scenario(
        "Dispense without signing or transmitting",
        ["dispense"],
    )
    run_scenario(
        "Skip signing, try to transmit",
        ["transmit"],
    )
    run_scenario(
        "Attempt to revert a dispensed prescription",
        ["sign", "transmit", "dispense", "transmit"],
    )
    run_scenario(
        "Attempt to cancel after dispensing",
        ["sign", "transmit", "dispense", "cancel"],
    )
    run_scenario(
        "Expire from drafted (guard blocks it)",
        ["expire"],
    )

    header("Sequence validator")
    run_validator_demo(
        "Accepted full lifecycle",
        ["sign", "transmit", "dispense"],
    )
    run_validator_demo(
        "Rejected double dispense",
        ["sign", "transmit", "dispense", "dispense"],
    )

    header("SQLite persistence")
    run_persistence_demo()

    header("Background expiry scheduler")
    run_scheduler_demo()

    header("FHIR MedicationRequest parsing")
    run_fhir_demo()


if __name__ == "__main__":
    main()
