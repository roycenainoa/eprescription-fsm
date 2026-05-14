"""Unit tests for the Prescription finite state machine."""

import pytest

from src.exceptions import InvalidTransitionError, TerminalStateError
from src.prescription import Prescription, TERMINAL_STATES


class TestInitialState:
    def test_new_prescription_starts_drafted(self):
        prescription = Prescription()
        assert prescription.state == "drafted"

    def test_new_prescription_is_not_terminal(self):
        prescription = Prescription()
        assert prescription.is_terminal is False

    def test_new_prescription_has_empty_history(self):
        prescription = Prescription()
        assert prescription.history == []


class TestStandardWorkflow:
    def test_full_lifecycle_drafted_to_dispensed(self):
        prescription = Prescription()
        prescription.trigger_event("sign")
        prescription.trigger_event("transmit")
        prescription.trigger_event("dispense")
        assert prescription.state == "dispensed"
        assert prescription.is_terminal is True

    def test_history_records_every_transition(self):
        prescription = Prescription()
        prescription.trigger_event("sign")
        prescription.trigger_event("transmit")
        prescription.trigger_event("dispense")
        assert prescription.history == ["signed", "transmitted", "dispensed"]

    def test_sign_moves_drafted_to_signed(self):
        prescription = Prescription()
        result = prescription.trigger_event("sign")
        assert result == "signed"

    def test_transmit_moves_signed_to_transmitted(self):
        prescription = Prescription()
        prescription.trigger_event("sign")
        result = prescription.trigger_event("transmit")
        assert result == "transmitted"

    def test_dispense_moves_transmitted_to_dispensed(self):
        prescription = Prescription()
        prescription.trigger_event("sign")
        prescription.trigger_event("transmit")
        result = prescription.trigger_event("dispense")
        assert result == "dispensed"


class TestExpiry:
    def test_expire_allowed_from_signed(self):
        prescription = Prescription()
        prescription.trigger_event("sign")
        prescription.trigger_event("expire")
        assert prescription.state == "expired"

    def test_expire_allowed_from_transmitted(self):
        prescription = Prescription()
        prescription.trigger_event("sign")
        prescription.trigger_event("transmit")
        prescription.trigger_event("expire")
        assert prescription.state == "expired"

    def test_expire_rejected_from_drafted(self):
        prescription = Prescription()
        with pytest.raises(InvalidTransitionError):
            prescription.trigger_event("expire")


class TestCancellation:
    def test_cancel_allowed_from_drafted(self):
        prescription = Prescription()
        prescription.trigger_event("cancel")
        assert prescription.state == "cancelled"

    def test_cancel_allowed_from_signed(self):
        prescription = Prescription()
        prescription.trigger_event("sign")
        prescription.trigger_event("cancel")
        assert prescription.state == "cancelled"

    def test_cancel_allowed_from_transmitted(self):
        prescription = Prescription()
        prescription.trigger_event("sign")
        prescription.trigger_event("transmit")
        prescription.trigger_event("cancel")
        assert prescription.state == "cancelled"


class TestTerminalStates:
    @pytest.mark.parametrize("terminal_state", sorted(TERMINAL_STATES))
    def test_terminal_states_block_every_event(self, terminal_state):
        prescription = Prescription()
        prescription.machine.set_state(terminal_state)
        for event in ("sign", "transmit", "dispense", "expire", "cancel"):
            with pytest.raises(TerminalStateError):
                prescription.trigger_event(event)

    def test_dispensed_cannot_revert_to_transmitted(self):
        prescription = Prescription()
        prescription.trigger_event("sign")
        prescription.trigger_event("transmit")
        prescription.trigger_event("dispense")
        with pytest.raises(TerminalStateError):
            prescription.trigger_event("transmit")

    def test_cancelled_cannot_be_dispensed(self):
        prescription = Prescription()
        prescription.trigger_event("cancel")
        with pytest.raises(TerminalStateError):
            prescription.trigger_event("dispense")

    def test_expired_cannot_be_dispensed(self):
        prescription = Prescription()
        prescription.trigger_event("sign")
        prescription.trigger_event("expire")
        with pytest.raises(TerminalStateError):
            prescription.trigger_event("dispense")


class TestIllegalTransitions:
    def test_dispense_rejected_from_drafted(self):
        prescription = Prescription()
        with pytest.raises(InvalidTransitionError):
            prescription.trigger_event("dispense")

    def test_dispense_rejected_from_signed(self):
        prescription = Prescription()
        prescription.trigger_event("sign")
        with pytest.raises(InvalidTransitionError):
            prescription.trigger_event("dispense")

    def test_transmit_rejected_from_drafted(self):
        prescription = Prescription()
        with pytest.raises(InvalidTransitionError):
            prescription.trigger_event("transmit")

    def test_sign_rejected_when_already_signed(self):
        prescription = Prescription()
        prescription.trigger_event("sign")
        with pytest.raises(InvalidTransitionError):
            prescription.trigger_event("sign")

    def test_unknown_event_rejected(self):
        prescription = Prescription()
        with pytest.raises(InvalidTransitionError):
            prescription.trigger_event("teleport")

    def test_rejected_event_does_not_mutate_state(self):
        prescription = Prescription()
        prescription.trigger_event("sign")
        original_state = prescription.state
        original_history = list(prescription.history)
        with pytest.raises(InvalidTransitionError):
            prescription.trigger_event("dispense")
        assert prescription.state == original_state
        assert prescription.history == original_history


class TestExceptionContent:
    def test_invalid_transition_error_carries_context(self):
        prescription = Prescription()
        with pytest.raises(InvalidTransitionError) as exc_info:
            prescription.trigger_event("dispense")
        assert exc_info.value.current_state == "drafted"
        assert exc_info.value.event == "dispense"

    def test_terminal_state_error_carries_context(self):
        prescription = Prescription()
        prescription.trigger_event("cancel")
        with pytest.raises(TerminalStateError) as exc_info:
            prescription.trigger_event("sign")
        assert exc_info.value.current_state == "cancelled"
        assert exc_info.value.event == "sign"
