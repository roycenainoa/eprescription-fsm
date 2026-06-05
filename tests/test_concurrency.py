"""Concurrency and stress tests for the Prescription FSM.

The concurrency tests verify that the reentrant lock around trigger_event
serialises competing dispatches so that the audit history cannot record
two transitions for the same logical step. The stress tests verify that
the FSM remains in a coherent state after thousands of rapid illegal
events and that no exception leaks beyond the typed exception hierarchy.
"""

from concurrent.futures import ThreadPoolExecutor

import pytest

from src.exceptions import InvalidTransitionError, TerminalStateError
from src.prescription import Prescription


class TestConcurrentTransitions:
    def test_only_one_thread_can_sign(self):
        """Ten threads race to sign the same prescription. The lock
        guarantees that exactly one transition is committed; the rest
        must observe the post-sign state and raise InvalidTransitionError
        because sign is no longer valid from signed."""
        prescription = Prescription(identifier="rx-concurrent-1")
        successes = []
        failures = []

        def attempt_sign():
            try:
                successes.append(prescription.trigger_event("sign"))
            except InvalidTransitionError as exc:
                failures.append(exc)

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(attempt_sign) for _ in range(10)]
            for future in futures:
                future.result()

        assert prescription.state == "signed"
        assert prescription.history == ["signed"]
        assert len(successes) == 1
        assert len(failures) == 9

    def test_full_lifecycle_under_contention(self):
        """One thread advances the prescription through its lifecycle
        while three other threads continuously attempt illegal events.
        The final state must still be dispensed and the audit history
        must reflect exactly the three legal transitions."""
        prescription = Prescription(identifier="rx-concurrent-2")

        def advance():
            prescription.trigger_event("sign")
            prescription.trigger_event("transmit")
            prescription.trigger_event("dispense")

        def attempt_illegal():
            for _ in range(50):
                try:
                    prescription.trigger_event("expire")
                except (InvalidTransitionError, TerminalStateError):
                    pass

        with ThreadPoolExecutor(max_workers=4) as executor:
            advance_future = executor.submit(advance)
            illegal_futures = [
                executor.submit(attempt_illegal) for _ in range(3)
            ]
            advance_future.result()
            for future in illegal_futures:
                future.result()

        assert prescription.state == "dispensed"
        assert prescription.history == ["signed", "transmitted", "dispensed"]

    def test_concurrent_cancels_only_commit_once(self):
        """Multiple threads racing to cancel a drafted prescription.
        Exactly one wins; the rest observe the cancelled terminal state
        and raise TerminalStateError."""
        prescription = Prescription(identifier="rx-concurrent-3")
        successes = []
        terminal_failures = []

        def attempt_cancel():
            try:
                successes.append(prescription.trigger_event("cancel"))
            except TerminalStateError as exc:
                terminal_failures.append(exc)

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(attempt_cancel) for _ in range(8)]
            for future in futures:
                future.result()

        assert prescription.state == "cancelled"
        assert prescription.history == ["cancelled"]
        assert len(successes) == 1
        assert len(terminal_failures) == 7


class TestStressInvalidTransitions:
    def test_rapid_invalid_transitions_do_not_mutate_state(self):
        """Two thousand illegal events should all raise the typed
        exception and leave the state and history exactly as they were
        before the loop started."""
        prescription = Prescription(identifier="rx-stress-1")
        prescription.trigger_event("sign")
        initial_state = prescription.state
        initial_history = list(prescription.history)

        errors = 0
        for _ in range(2000):
            try:
                # dispense is illegal from signed
                prescription.trigger_event("dispense")
            except InvalidTransitionError:
                errors += 1

        assert errors == 2000
        assert prescription.state == initial_state
        assert prescription.history == initial_history

    def test_rapid_events_against_terminal_state(self):
        """After reaching a terminal state, every dispatched event must
        be rejected with TerminalStateError. The loop hammers all five
        defined events 500 times each and verifies the count."""
        prescription = Prescription(identifier="rx-stress-2")
        prescription.trigger_event("sign")
        prescription.trigger_event("transmit")
        prescription.trigger_event("dispense")

        errors = 0
        events = ("sign", "transmit", "dispense", "expire", "cancel")
        for event in events * 500:
            try:
                prescription.trigger_event(event)
            except TerminalStateError:
                errors += 1

        assert errors == 2500
        assert prescription.state == "dispensed"
        assert prescription.history == ["signed", "transmitted", "dispensed"]

    def test_unknown_events_under_stress(self):
        """The FSM must remain coherent even when bombarded with event
        names that are not part of the declared alphabet."""
        prescription = Prescription(identifier="rx-stress-3")
        prescription.trigger_event("sign")

        errors = 0
        for name in ("teleport", "explode", "noop", "approve", "void") * 200:
            try:
                prescription.trigger_event(name)
            except InvalidTransitionError:
                errors += 1

        assert errors == 1000
        assert prescription.state == "signed"
        assert prescription.history == ["signed"]
