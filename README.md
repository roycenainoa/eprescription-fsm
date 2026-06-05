# Electronic Prescription Lifecycle FSM

Reference implementation that accompanies the research report
*Electronic Prescription Lifecycle Modeling with Finite State Machines*
(Cornwell, 2026). The project models the lifecycle of an electronic
prescription as a deterministic finite state machine implemented in Python
with the `transitions` library, and now includes a relational persistence
layer, a background expiry scheduler, a FHIR `MedicationRequest` parser,
and a concurrency-safe public dispatch method.

## States

The model defines six discrete states:

- `drafted` (initial state)
- `signed`
- `transmitted`
- `dispensed` (terminal)
- `expired` (terminal)
- `cancelled` (terminal)

## Transitions

| Event      | Source states                          | Destination |
|------------|----------------------------------------|-------------|
| `sign`     | `drafted`                              | `signed`    |
| `transmit` | `signed`                               | `transmitted` |
| `dispense` | `transmitted`                          | `dispensed` |
| `expire`   | `signed`, `transmitted`                | `expired`   |
| `cancel`   | `drafted`, `signed`, `transmitted`     | `cancelled` |

Any event that is not defined for the active state raises an
`InvalidTransitionError`. Any event dispatched against a terminal state
raises a `TerminalStateError`.

## Project layout

```
eprescription-fsm/
├── src/
│   ├── exceptions.py      # Custom exception hierarchy
│   ├── prescription.py    # FSM model with reentrant lock
│   ├── validator.py       # Sequence validator
│   ├── storage.py         # SQLAlchemy persistence layer
│   ├── scheduler.py       # Background expiry scheduler
│   └── fhir.py            # FHIR MedicationRequest parser
├── tests/
│   ├── test_prescription.py
│   ├── test_validator.py
│   ├── test_storage.py
│   ├── test_scheduler.py
│   ├── test_fhir.py
│   └── test_concurrency.py
├── docs/
│   └── implementation_and_testing.md
├── demo.py
├── requirements.txt
└── README.md
```

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Running the tests

```bash
pytest -v
```

The suite runs 76 cases covering the FSM core, the validator,
persistence round trips, scheduler firing and cancellation, FHIR
parsing, concurrency under contention, and stress against rapid
illegal events.

## Running the demo

A script at the repository root walks through accepted workflows,
rejected workflows, and the sequence validator. It prints the events
dispatched, the resulting state transitions, and the rejection reason
when a guard blocks an illegal input.

```bash
python demo.py
```

## Minimal usage example

```python
from src.prescription import Prescription

prescription = Prescription(identifier="rx-001")
prescription.trigger_event("sign")
prescription.trigger_event("transmit")
prescription.trigger_event("dispense")
print(prescription.state)        # "dispensed"
print(prescription.is_terminal)  # True
```

## Persistence with SQLAlchemy

The `storage` module exposes a `PrescriptionRepository` that serialises
the FSM state and audit history to an SQLite database. Persistence is
implemented through a repository pattern so that the `Prescription`
class itself has no dependency on the database.

```python
from src.prescription import Prescription
from src.storage import PrescriptionRepository, create_engine_and_session

_, Session = create_engine_and_session("sqlite:///prescriptions.db")
session = Session()
repo = PrescriptionRepository(session)

prescription = Prescription(identifier="rx-001")
prescription.trigger_event("sign")
repo.save(prescription)

# After a process restart, reload from the same database
restored = repo.load("rx-001")
restored.trigger_event("transmit")
repo.save(restored)
session.close()
```

The repository uses the prescription identifier as the natural key, so
calling `save` again for the same identifier updates the existing row
in place.

## Background expiry scheduler

The `scheduler` module exposes `ExpiryScheduler`, which uses
`threading.Timer` to dispatch the `expire` event after a configured
delay. The FSM core stays synchronous and deterministic; the scheduler
is a thin wrapper that decides when to trigger the event.

```python
from src.prescription import Prescription
from src.scheduler import ExpiryScheduler

prescription = Prescription(identifier="rx-002")
prescription.trigger_event("sign")

scheduler = ExpiryScheduler(prescription, delay_seconds=86400)  # 24 hours
scheduler.start()

# If the prescription is dispensed before the timer fires, cancel it
prescription.trigger_event("transmit")
prescription.trigger_event("dispense")
scheduler.cancel()
```

A timer that fires while the prescription is already in a terminal
state is silently ignored, so the scheduler is safe to leave running
across the full lifecycle.

## FHIR MedicationRequest parsing

The `fhir` module exposes `prescription_from_fhir`, which accepts a
FHIR R4 `MedicationRequest` payload as a Python dictionary and returns
a `Prescription` initialised to the equivalent FSM state. Status
values are mapped as follows:

| FHIR status   | FSM state   |
|---------------|-------------|
| `draft`       | `drafted`   |
| `active`      | `signed`    |
| `completed`   | `dispensed` |
| `cancelled`   | `cancelled` |
| `stopped`     | `cancelled` |
| `ended`       | `expired`   |

Statuses outside this mapping raise `FHIRParseError`.

```python
from src.fhir import prescription_from_fhir

payload = {
    "resourceType": "MedicationRequest",
    "id": "rx-from-fhir",
    "status": "active",
    "intent": "order",
    "medicationCodeableConcept": {"text": "Amoxicillin 500mg"},
    "subject": {"reference": "Patient/example"},
}
prescription = prescription_from_fhir(payload)
prescription.trigger_event("transmit")
```

## Concurrency

`Prescription.trigger_event` is guarded by a reentrant lock, so
multiple threads may race against the same instance without corrupting
the audit history or producing inconsistent reads. Concurrency is
verified by the `tests/test_concurrency.py` suite, which includes both
contention tests (multiple threads racing to advance the same
prescription) and stress tests (thousands of rapid illegal events
dispatched against a single instance).
