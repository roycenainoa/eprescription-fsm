"""Demonstration script for the electronic prescription FSM.

Runs through a representative set of scenarios so that a reader can verify
the model behaviour without writing Python interactively. Each scenario
prints the events dispatched, the resulting state, and the audit history
or the rejection reason.

Usage:
    python demo.py
"""

from src.exceptions import InvalidTransitionError, TerminalStateError
from src.prescription import Prescription
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


if __name__ == "__main__":
    main()
