# 6. Implementation

The implementation translates the formal deterministic finite automaton
defined in Section 5 into a small, auditable Python package. The complete
source code is available in the public GitHub repository at
`https://github.com/roycenainoa/eprescription-fsm`. The project depends
on the `transitions` library (version 0.9.2) for the underlying state
machine engine and on `pytest` (version 8.3.3) for the test suite. No
machine learning, database, or networking components are introduced,
which preserves the deterministic and analytically transparent behaviour
required by the model.

## 6.1 Module Structure

The package is organised into three modules inside the `src` directory.
The `exceptions` module defines a typed exception hierarchy. The
`prescription` module exposes the `Prescription` class, which binds a
finite set of states and a transition function to a model object. The
`validator` module provides a thin wrapper that consumes a list of event
symbols and reports whether the sequence is accepted by the automaton.
A separate `tests` directory contains pytest cases that exercise both
the model and the validator.

## 6.2 The Prescription Class

The `Prescription` class is the core artefact of the implementation. On
construction, it instantiates a `transitions.Machine` bound to itself,
passes the six declared states, and registers the transition function as
a list of dictionaries. Each dictionary maps an event trigger to its
permitted source states and a single destination state, which directly
mirrors the mathematical transition function `δ` discussed in Section 4.
The initial state is set to `drafted`. The constructor argument
`auto_transitions=False` is set so that the library does not synthesise
shortcut triggers (for example, `to_dispensed`), which would otherwise
introduce paths that violate the formal model. The argument
`ignore_invalid_triggers=False` ensures that any unauthorised event
raises a `MachineError` rather than silently failing.

```python
STATES = [
    "drafted", "signed", "transmitted",
    "dispensed", "expired", "cancelled",
]

TRANSITIONS = [
    {"trigger": "sign", "source": "drafted", "dest": "signed"},
    {"trigger": "transmit", "source": "signed", "dest": "transmitted"},
    {"trigger": "dispense", "source": "transmitted", "dest": "dispensed"},
    {"trigger": "expire", "source": ["signed", "transmitted"], "dest": "expired"},
    {"trigger": "cancel",
     "source": ["drafted", "signed", "transmitted"],
     "dest": "cancelled"},
]

class Prescription:
    def __init__(self, identifier=None):
        self.identifier = identifier
        self.history = []
        self.machine = Machine(
            model=self,
            states=STATES,
            transitions=TRANSITIONS,
            initial="drafted",
            auto_transitions=False,
            send_event=True,
            after_state_change="_record_transition",
            ignore_invalid_triggers=False,
        )
```

Every successful transition triggers an `after_state_change` callback
named `_record_transition`, which appends the new state to an internal
`history` list. The history acts as a deterministic audit trail. Because
the callback fires only after the library has committed a transition,
rejected events leave the history untouched. This guarantee is verified
explicitly by the test `test_rejected_event_does_not_mutate_state`.

## 6.3 Guard Logic and Exception Handling

The default behaviour of the `transitions` library is to raise a generic
`MachineError` for any unauthorised input. While sufficient for control
flow, this exception type does not distinguish between two semantically
different rejection reasons that matter for clinical auditing. The first
case is an event that is simply undefined for the active state, such as
attempting to dispense a drafted prescription. The second case is an
event dispatched against a prescription that has already entered a
terminal state. The implementation therefore exposes a single dispatch
method, `trigger_event`, that wraps the library call and routes each
class of failure to a dedicated typed exception.

```python
def trigger_event(self, event_name):
    if self.state in TERMINAL_STATES:
        raise TerminalStateError(self.state, event_name)
    try:
        self.trigger(event_name)
    except (MachineError, AttributeError) as exc:
        raise InvalidTransitionError(self.state, event_name) from exc
    return self.state
```

Terminal states are pre-checked before any call into the library, which
guarantees that the three accept states (`dispensed`, `expired`,
`cancelled`) possess no outbound transitions. This satisfies the formal
requirement stated in Section 5 that terminal states must not mutate
under further input. The `TerminalStateError` and
`InvalidTransitionError` exceptions both store the offending state and
event name as attributes, which allows downstream auditing code to
generate structured log records without parsing exception messages.

## 6.4 Sequence Validator

The `validate_sequence` function in the `validator` module realises the
formal definition of language acceptance from automata theory. Given a
list of event names, it instantiates a fresh `Prescription` and dispatches
each event in order. The first event that raises either exception halts
processing, and the function returns a `ValidationResult` dataclass that
captures the accepted flag, the final state, the prefix of events that
were consumed before rejection, the offending event, and a human-readable
rejection reason. An empty sequence is accepted with a final state of
`drafted`, which is consistent with the convention that the empty input
leaves the automaton in its initial state.

## 6.5 Verification

Correctness is established through 38 pytest cases that cover the
standard workflow, every terminal state, every guarded transition for
expiry and cancellation, and a representative set of illegal inputs.
Parametrised tests confirm that every terminal state rejects every
defined event. The full suite executes in under one second, which makes
it suitable for inclusion in a continuous integration pipeline. In
addition to the automated tests, the repository ships a `demo.py` script
at the project root that walks through accepted workflows, rejected
workflows, and two sequence validator examples; the script gives a
reviewer a single command path to observe the model behaviour without
writing Python interactively. The testing approach and detailed results
are presented in Section 7.

# 7. Testing

The implementation is verified through a structured suite of unit tests
written with the pytest framework. The deterministic nature of the
finite state machine makes it well suited to unit level verification,
because every transition produces an observable result that depends
only on the current state and the dispatched event. The test suite is
organised so that each test category maps back to a formal property
asserted in Section 5, which supports requirement traceability and
allows a reviewer to verify that the implemented model satisfies the
mathematical specification.

## 7.1 Testing Methodology

Pytest was selected for the suite because it provides a minimal,
declarative test syntax, native support for parametrised cases, and
clear failure reporting without requiring an inheritance hierarchy.
Tests are written in a black box style: each case interacts with the
`Prescription` model exclusively through its public dispatch method,
`trigger_event`, and observes the resulting state, the audit history,
and any raised exceptions. This style ensures that the tests document
expected behaviour rather than implementation details, and remain valid
even if the internal callback mechanism of the `transitions` library is
later adjusted.

The suite is split into two modules. The module
`tests/test_prescription.py` verifies the finite state machine itself,
including state transitions, guard logic, and exception semantics. The
module `tests/test_validator.py` exercises the sequence acceptor
described in Section 6.4, which provides end to end validation of input
sequences against the automaton.

## 7.2 Test Categories

The suite contains 38 cases distributed across eight categories. Each
category targets a specific property of the formal model defined in
Section 5.

| Category                     | Tests | Property verified                                         |
|------------------------------|------:|-----------------------------------------------------------|
| Initial state correctness    |     3 | The prescription starts in `drafted` with empty history   |
| Standard workflow            |     5 | drafted → signed → transmitted → dispensed                |
| Expiry guard                 |     3 | `expire` only valid from `signed` or `transmitted`        |
| Cancellation guard           |     3 | `cancel` valid from any pre dispensing state              |
| Terminal state enforcement   |     6 | No event mutates a terminal state                         |
| Illegal transition rejection |     6 | Undefined events raise `InvalidTransitionError`           |
| Exception payload integrity  |     2 | Exceptions carry the offending state and event name       |
| Sequence validator           |    10 | Acceptor reproduces the FSM acceptance behaviour          |

Several cases are parametrised. The terminal state category uses pytest
parametrisation to dispatch all five defined events against each of the
three terminal states, which produces fifteen logical assertions from a
single test function. This pattern compacts the test file while still
covering every illegal combination of terminal state and event.

One case deserves explicit mention because it protects a subtle
invariant. The case `test_rejected_event_does_not_mutate_state`
dispatches an illegal event against a prescription in the `signed`
state, asserts that the exception is raised, and then confirms that
both the state attribute and the audit history are unchanged. This
verifies that the `after_state_change` callback described in Section
6.2 fires only on a committed transition, which is the property that
prevents rejected events from polluting the audit trail. The companion
suite for the validator follows the same principle at the sequence
level: the `consumed` field of the returned `ValidationResult` records
only the prefix of events that were committed before the first
rejection, so an external auditor can reconstruct the exact point at
which an invalid clinical sequence was halted.

## 7.3 Results

The full suite runs in 0.04 seconds on a standard laptop and reports
all 38 cases as passing. Because the tests do not depend on the
network, the file system, or a wall clock, the runtime is stable across
executions and the suite is suitable for inclusion in a continuous
integration pipeline. A reviewer can reproduce the result with a single
command after installing the dependencies:

```bash
pytest -v
```

The verbose flag prints the name of every test case and its outcome,
which makes the per category coverage immediately visible in the
console output.

## 7.4 Limitations

The suite establishes correctness of the deterministic transition
function but does not address several concerns that would arise in a
production deployment. Real time based expiry is modelled by an explicit
`expire` event rather than by a clock; the implementation assumes that
an external scheduler dispatches this event when the prescription
validity window elapses. The state of a prescription lives in memory
only, so persistence and recovery from a crashed process are out of
scope. Concurrent access from multiple processes is also not tested,
because the model assumes a single owning process per prescription
instance. These limitations are intentional and follow from the
analytical scope defined in Section 1; they are revisited as candidate
extensions in the Conclusion.
