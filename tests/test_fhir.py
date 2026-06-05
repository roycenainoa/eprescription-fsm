"""Tests for the FHIR MedicationRequest parser."""

import pytest

from src.fhir import FHIRParseError, prescription_from_fhir


def _payload(status: str = "draft", identifier: str = "rx-fhir-1") -> dict:
    """Build a minimal but well-formed MedicationRequest payload."""
    return {
        "resourceType": "MedicationRequest",
        "id": identifier,
        "status": status,
        "intent": "order",
        "medicationCodeableConcept": {"text": "Amoxicillin 500mg"},
        "subject": {"reference": "Patient/example"},
    }


class TestStatusMapping:
    def test_draft_maps_to_drafted(self):
        prescription = prescription_from_fhir(_payload("draft"))
        assert prescription.state == "drafted"
        assert prescription.history == []

    def test_active_maps_to_signed(self):
        prescription = prescription_from_fhir(_payload("active"))
        assert prescription.state == "signed"
        assert prescription.history == ["signed"]

    def test_completed_maps_to_dispensed(self):
        prescription = prescription_from_fhir(_payload("completed"))
        assert prescription.state == "dispensed"
        assert prescription.is_terminal is True

    def test_cancelled_maps_to_cancelled(self):
        prescription = prescription_from_fhir(_payload("cancelled"))
        assert prescription.state == "cancelled"
        assert prescription.is_terminal is True

    def test_stopped_maps_to_cancelled(self):
        prescription = prescription_from_fhir(_payload("stopped"))
        assert prescription.state == "cancelled"

    def test_ended_maps_to_expired(self):
        prescription = prescription_from_fhir(_payload("ended"))
        assert prescription.state == "expired"


class TestIdentifierExtraction:
    def test_identifier_list_takes_precedence_over_id(self):
        payload = _payload(identifier="rx-from-id")
        payload["identifier"] = [{"value": "rx-from-list"}]
        prescription = prescription_from_fhir(payload)
        assert prescription.identifier == "rx-from-list"

    def test_falls_back_to_top_level_id(self):
        payload = _payload(identifier="rx-from-id")
        prescription = prescription_from_fhir(payload)
        assert prescription.identifier == "rx-from-id"

    def test_skips_malformed_identifier_entries(self):
        payload = _payload(identifier="rx-from-id")
        payload["identifier"] = [
            {"system": "no-value-field"},
            {"value": ""},
            {"value": "rx-valid"},
        ]
        prescription = prescription_from_fhir(payload)
        assert prescription.identifier == "rx-valid"


class TestParseErrors:
    def test_non_dict_payload_rejected(self):
        with pytest.raises(FHIRParseError):
            prescription_from_fhir("not a dict")

    def test_wrong_resource_type_rejected(self):
        with pytest.raises(FHIRParseError):
            prescription_from_fhir(
                {"resourceType": "Observation", "id": "rx-1", "status": "draft"}
            )

    def test_missing_identifier_rejected(self):
        payload = _payload()
        del payload["id"]
        with pytest.raises(FHIRParseError):
            prescription_from_fhir(payload)

    def test_unmapped_status_rejected(self):
        with pytest.raises(FHIRParseError):
            prescription_from_fhir(_payload("entered-in-error"))

    def test_missing_status_rejected(self):
        payload = _payload()
        del payload["status"]
        with pytest.raises(FHIRParseError):
            prescription_from_fhir(payload)


class TestLoadedPrescriptionIsFunctional:
    def test_loaded_active_prescription_can_be_transmitted(self):
        prescription = prescription_from_fhir(_payload("active"))
        result = prescription.trigger_event("transmit")
        assert result == "transmitted"

    def test_loaded_drafted_prescription_can_be_signed(self):
        prescription = prescription_from_fhir(_payload("draft"))
        result = prescription.trigger_event("sign")
        assert result == "signed"
