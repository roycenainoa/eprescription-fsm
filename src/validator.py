"""Sequence validator built on top of the Prescription state machine.

A deterministic finite automaton accepts or rejects a sequence of input
symbols based on its final state and the validity of every intermediate
transition. This module exposes a thin wrapper that processes a list of
event names against a fresh prescription instance and reports whether the
sequence is accepted by the machine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .exceptions import InvalidTransitionError, TerminalStateError
from .prescription import Prescription


@dataclass
class ValidationResult:
    """Outcome of running an input sequence through the state machine."""

    accepted: bool
    final_state: str
    consumed: List[str] = field(default_factory=list)
    rejection_reason: Optional[str] = None
    rejected_event: Optional[str] = None


def validate_sequence(events: List[str]) -> ValidationResult:
    """Run a sequence of events through a fresh prescription model.

    The sequence is accepted only when every event corresponds to a
    permitted transition for the current state. The first illegal event
    halts processing and is reported in the result object.
    """
    prescription = Prescription()
    consumed: List[str] = []

    for event in events:
        try:
            prescription.trigger_event(event)
        except (InvalidTransitionError, TerminalStateError) as exc:
            return ValidationResult(
                accepted=False,
                final_state=prescription.state,
                consumed=consumed,
                rejection_reason=str(exc),
                rejected_event=event,
            )
        consumed.append(event)

    return ValidationResult(
        accepted=True,
        final_state=prescription.state,
        consumed=consumed,
    )
