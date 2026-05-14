"""Deterministic finite state machine model of the electronic prescription
lifecycle.

The model defines six discrete states and a strict transition function that
mirrors the formal definition of a deterministic finite automaton. Every
event must correspond to a permitted transition for the current state;
unauthorised inputs are rejected by raising a typed exception.
"""

from __future__ import annotations

from typing import List, Optional

from transitions import Machine, MachineError

from .exceptions import InvalidTransitionError, TerminalStateError


STATES: List[str] = [
    "drafted",
    "signed",
    "transmitted",
    "dispensed",
    "expired",
    "cancelled",
]

TERMINAL_STATES = frozenset({"dispensed", "expired", "cancelled"})

TRANSITIONS = [
    {"trigger": "sign", "source": "drafted", "dest": "signed"},
    {"trigger": "transmit", "source": "signed", "dest": "transmitted"},
    {"trigger": "dispense", "source": "transmitted", "dest": "dispensed"},
    {"trigger": "expire", "source": ["signed", "transmitted"], "dest": "expired"},
    {
        "trigger": "cancel",
        "source": ["drafted", "signed", "transmitted"],
        "dest": "cancelled",
    },
]


class Prescription:
    """Finite state machine representation of a single prescription.

    The class wraps the transitions library Machine so that every event call
    is routed through a guard that rejects illegal inputs. The guard
    distinguishes between transitions blocked because the prescription has
    already reached a terminal state and transitions blocked because the
    requested event is not defined for the active state.
    """

    def __init__(self, identifier: Optional[str] = None) -> None:
        self.identifier = identifier
        self.history: List[str] = []
        self.machine = Machine(
            model=self,
            states=STATES,
            transitions=TRANSITIONS,
            initial="drafted",
            auto_transitions=False,
            send_event=True,
            after_state_change="_record_transition",
            ignore_invalid_triggers=False,
        )

    def _record_transition(self, event) -> None:
        """Append the destination state to the audit history after every
        successful transition. Invoked by the transitions callback hook."""
        self.history.append(self.state)

    def trigger_event(self, event_name: str) -> str:
        """Dispatch an event by name through the state machine.

        Wraps the underlying trigger call so that the library MachineError is
        translated into a domain specific exception. Terminal state attempts
        are reported separately from generic invalid transitions to support
        clearer auditing.
        """
        if self.state in TERMINAL_STATES:
            raise TerminalStateError(self.state, event_name)
        try:
            self.trigger(event_name)
        except (MachineError, AttributeError) as exc:
            raise InvalidTransitionError(self.state, event_name) from exc
        return self.state

    @property
    def is_terminal(self) -> bool:
        """True when the prescription has reached a terminal accept state."""
        return self.state in TERMINAL_STATES
