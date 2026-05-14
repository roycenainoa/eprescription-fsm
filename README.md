# Electronic Prescription Lifecycle FSM

Reference implementation that accompanies the research report
*Electronic Prescription Lifecycle Modeling with Finite State Machines*
(Cornwell, 2026). The project models the lifecycle of an electronic
prescription as a deterministic finite state machine implemented in Python
with the `transitions` library.

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
│   ├── prescription.py    # FSM model
│   └── validator.py       # Sequence validator
├── tests/
│   ├── test_prescription.py
│   └── test_validator.py
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
