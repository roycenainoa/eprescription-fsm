"""Unit tests for the sequence validator."""

from src.validator import validate_sequence


class TestAcceptedSequences:
    def test_empty_sequence_accepted_in_initial_state(self):
        result = validate_sequence([])
        assert result.accepted is True
        assert result.final_state == "drafted"

    def test_full_lifecycle_accepted(self):
        result = validate_sequence(["sign", "transmit", "dispense"])
        assert result.accepted is True
        assert result.final_state == "dispensed"
        assert result.consumed == ["sign", "transmit", "dispense"]

    def test_cancel_immediately_after_drafting_accepted(self):
        result = validate_sequence(["cancel"])
        assert result.accepted is True
        assert result.final_state == "cancelled"

    def test_signed_then_expired_accepted(self):
        result = validate_sequence(["sign", "expire"])
        assert result.accepted is True
        assert result.final_state == "expired"

    def test_transmitted_then_expired_accepted(self):
        result = validate_sequence(["sign", "transmit", "expire"])
        assert result.accepted is True
        assert result.final_state == "expired"


class TestRejectedSequences:
    def test_skipping_signature_rejected(self):
        result = validate_sequence(["transmit", "dispense"])
        assert result.accepted is False
        assert result.rejected_event == "transmit"
        assert result.final_state == "drafted"

    def test_double_dispense_rejected(self):
        result = validate_sequence(
            ["sign", "transmit", "dispense", "dispense"]
        )
        assert result.accepted is False
        assert result.rejected_event == "dispense"
        assert result.final_state == "dispensed"
        assert result.consumed == ["sign", "transmit", "dispense"]

    def test_cancel_after_dispense_rejected(self):
        result = validate_sequence(
            ["sign", "transmit", "dispense", "cancel"]
        )
        assert result.accepted is False
        assert result.rejected_event == "cancel"

    def test_expire_before_signing_rejected(self):
        result = validate_sequence(["expire"])
        assert result.accepted is False
        assert result.rejected_event == "expire"

    def test_rejection_reason_is_populated(self):
        result = validate_sequence(["dispense"])
        assert result.accepted is False
        assert result.rejection_reason is not None
        assert "dispense" in result.rejection_reason
