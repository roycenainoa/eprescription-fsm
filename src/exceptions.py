"""Custom exceptions for the electronic prescription finite state machine."""


class PrescriptionFSMError(Exception):
    """Base exception for all prescription state machine errors."""


class InvalidTransitionError(PrescriptionFSMError):
    """Raised when an event is triggered that is not authorised from the
    current state of the prescription."""

    def __init__(self, current_state: str, event: str) -> None:
        self.current_state = current_state
        self.event = event
        message = (
            f"Illegal transition: event '{event}' is not permitted "
            f"from state '{current_state}'."
        )
        super().__init__(message)


class TerminalStateError(PrescriptionFSMError):
    """Raised when an event is triggered against a prescription that has
    already reached a terminal state (dispensed, expired, cancelled)."""

    def __init__(self, current_state: str, event: str) -> None:
        self.current_state = current_state
        self.event = event
        message = (
            f"Terminal state violation: state '{current_state}' is final "
            f"and cannot process the event '{event}'."
        )
        super().__init__(message)
