"""FHIR MedicationRequest parsing adapter.

Accepts a FHIR MedicationRequest payload represented as a Python
dictionary and constructs a Prescription instance initialised to the
equivalent FSM state. The mapping is intentionally narrow: it covers
only the status values that align directly with the six declared
states of the model. Statuses outside this mapping are rejected so
that callers cannot smuggle the FSM into an undefined configuration.

The parser performs only structural validation. Full FHIR conformance
(profile validation, terminology binding, cross-resource references)
is out of scope and would be delegated to a dedicated FHIR library in
a production deployment.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .prescription import Prescription


# Mapping from FHIR MedicationRequest.status values to FSM states.
# The values on the left are defined by HL7 FHIR R4 for the
# MedicationRequest resource. Values not present here are rejected.
FHIR_STATUS_TO_FSM_STATE: Dict[str, str] = {
    "draft": "drafted",
    "active": "signed",
    "completed": "dispensed",
    "cancelled": "cancelled",
    "stopped": "cancelled",
    "ended": "expired",
}


class FHIRParseError(ValueError):
    """Raised when a payload cannot be parsed as a MedicationRequest."""


def prescription_from_fhir(payload: Any) -> Prescription:
    """Build a Prescription from a FHIR MedicationRequest JSON dictionary.

    The function verifies the resource type, extracts the identifier
    and the status, maps the FHIR status to one of the six declared
    FSM states, and returns a Prescription instance set to that state.
    When the resolved state is not the initial state, the audit
    history is seeded with the destination state so that a subsequent
    persistence round trip yields a coherent record.
    """
    if not isinstance(payload, dict):
        raise FHIRParseError("Payload must be a JSON object (Python dict).")

    resource_type = payload.get("resourceType")
    if resource_type != "MedicationRequest":
        raise FHIRParseError(
            f"Unsupported resourceType '{resource_type}'. "
            "Expected 'MedicationRequest'."
        )

    identifier = _extract_identifier(payload)
    if identifier is None:
        raise FHIRParseError("MedicationRequest is missing an identifier.")

    status = payload.get("status")
    if status not in FHIR_STATUS_TO_FSM_STATE:
        raise FHIRParseError(
            f"FHIR status '{status}' is not mapped to an FSM state."
        )

    fsm_state = FHIR_STATUS_TO_FSM_STATE[status]
    prescription = Prescription(identifier=identifier)

    # The default initial state of a fresh Prescription is "drafted".
    # Only adjust the machine when the resolved state differs, so that
    # the audit history reflects a real arrival rather than a no-op.
    if fsm_state != "drafted":
        prescription.machine.set_state(fsm_state)
        prescription.history.append(fsm_state)

    return prescription


def _extract_identifier(payload: Dict[str, Any]) -> Optional[str]:
    """Pull the first usable identifier value from the payload.

    FHIR MedicationRequest supports both a top level id field and a
    list of identifier objects. The list takes precedence because it
    is the canonical place to store business identifiers; the top
    level id is used as a fallback for compact mock payloads.
    """
    identifiers = payload.get("identifier")
    if isinstance(identifiers, list):
        for entry in identifiers:
            if isinstance(entry, dict):
                value = entry.get("value")
                if isinstance(value, str) and value:
                    return value

    fallback = payload.get("id")
    if isinstance(fallback, str) and fallback:
        return fallback
    return None
