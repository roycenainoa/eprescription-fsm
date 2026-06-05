"""Background scheduler that drives the temporal expire event.

Uses the standard library threading module to dispatch the expire event
after a configured delay. The FSM core remains synchronous and
deterministic; this module is a thin wrapper that decides WHEN to
trigger the event rather than HOW the transition is processed. The
scheduled timer is cancelled either explicitly by the caller or
implicitly when the prescription has already transitioned out of an
expiry-eligible state before the timer fires.

The timer thread is marked as a daemon so it cannot block process exit
if a scheduler is left running by accident.
"""

from __future__ import annotations

import threading
from typing import Optional

from .exceptions import InvalidTransitionError, TerminalStateError
from .prescription import Prescription


class ExpiryScheduler:
    """Manages a single-shot timer that fires the expire event.

    The scheduler owns at most one active timer at a time. Calling start
    while a timer is already pending cancels the previous timer and
    schedules a fresh one. This makes the API safe to call from event
    handlers that re-arm the timer after each state change.
    """

    def __init__(self, prescription: Prescription, delay_seconds: float) -> None:
        if delay_seconds <= 0:
            raise ValueError("delay_seconds must be positive.")
        self.prescription = prescription
        self.delay_seconds = delay_seconds
        self._timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()

    def start(self) -> None:
        """Schedule the expire event to fire after the configured delay."""
        with self._lock:
            self._cancel_existing()
            self._timer = threading.Timer(self.delay_seconds, self._fire)
            self._timer.daemon = True
            self._timer.start()

    def cancel(self) -> None:
        """Cancel a pending expiry timer, if any. Safe to call repeatedly."""
        with self._lock:
            self._cancel_existing()

    @property
    def is_pending(self) -> bool:
        """True while a timer is scheduled and has not yet fired."""
        with self._lock:
            return self._timer is not None and self._timer.is_alive()

    def _cancel_existing(self) -> None:
        # Internal helper. Caller must hold self._lock.
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _fire(self) -> None:
        """Dispatch the expire event when the timer elapses.

        The prescription may have moved to a terminal state or out of an
        expiry-eligible state between scheduling and firing. Both
        rejection types are swallowed because they represent expected
        races rather than programming errors.
        """
        try:
            self.prescription.trigger_event("expire")
        except (InvalidTransitionError, TerminalStateError):
            pass
