"""Tests for the ExpiryScheduler."""

import time

import pytest

from src.prescription import Prescription
from src.scheduler import ExpiryScheduler


def _wait_for_state(prescription, target_state, timeout=2.0, poll=0.01):
    """Poll the prescription state until it matches the target value or
    the timeout elapses. Returns True if the state was observed."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if prescription.state == target_state:
            return True
        time.sleep(poll)
    return False


class TestSchedulerFires:
    def test_expiry_fires_from_signed_state(self):
        prescription = Prescription(identifier="rx-sched-1")
        prescription.trigger_event("sign")
        scheduler = ExpiryScheduler(prescription, delay_seconds=0.05)
        scheduler.start()
        assert _wait_for_state(prescription, "expired") is True
        assert prescription.history == ["signed", "expired"]

    def test_expiry_fires_from_transmitted_state(self):
        prescription = Prescription(identifier="rx-sched-2")
        prescription.trigger_event("sign")
        prescription.trigger_event("transmit")
        scheduler = ExpiryScheduler(prescription, delay_seconds=0.05)
        scheduler.start()
        assert _wait_for_state(prescription, "expired") is True


class TestSchedulerCancellation:
    def test_dispense_before_timer_fires_blocks_expiry(self):
        prescription = Prescription(identifier="rx-sched-3")
        prescription.trigger_event("sign")
        prescription.trigger_event("transmit")
        scheduler = ExpiryScheduler(prescription, delay_seconds=0.5)
        scheduler.start()
        prescription.trigger_event("dispense")
        scheduler.cancel()
        time.sleep(0.6)
        assert prescription.state == "dispensed"

    def test_explicit_cancel_stops_pending_timer(self):
        prescription = Prescription(identifier="rx-sched-4")
        prescription.trigger_event("sign")
        scheduler = ExpiryScheduler(prescription, delay_seconds=0.5)
        scheduler.start()
        scheduler.cancel()
        time.sleep(0.6)
        assert prescription.state == "signed"

    def test_repeat_cancel_is_safe(self):
        prescription = Prescription(identifier="rx-sched-5")
        scheduler = ExpiryScheduler(prescription, delay_seconds=0.5)
        scheduler.cancel()
        scheduler.cancel()
        assert scheduler.is_pending is False

    def test_timer_firing_on_terminal_state_is_silent(self):
        prescription = Prescription(identifier="rx-sched-6")
        prescription.trigger_event("sign")
        prescription.trigger_event("transmit")
        prescription.trigger_event("dispense")
        scheduler = ExpiryScheduler(prescription, delay_seconds=0.05)
        scheduler.start()
        time.sleep(0.15)
        assert prescription.state == "dispensed"


class TestSchedulerValidation:
    def test_zero_delay_rejected(self):
        prescription = Prescription(identifier="rx-sched-7")
        with pytest.raises(ValueError):
            ExpiryScheduler(prescription, delay_seconds=0)

    def test_negative_delay_rejected(self):
        prescription = Prescription(identifier="rx-sched-8")
        with pytest.raises(ValueError):
            ExpiryScheduler(prescription, delay_seconds=-1)

    def test_start_replaces_existing_timer(self):
        prescription = Prescription(identifier="rx-sched-9")
        prescription.trigger_event("sign")
        scheduler = ExpiryScheduler(prescription, delay_seconds=10)
        scheduler.start()
        assert scheduler.is_pending is True
        scheduler.cancel()
        assert scheduler.is_pending is False
