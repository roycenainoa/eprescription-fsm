# 6. Implementation

The implementation translates the formal deterministic finite automaton
defined in Section 5 into a small, auditable Python package. The complete
source code is available in the public GitHub repository at
`<INSERT GITHUB REPOSITORY URL HERE>`. The project depends on the
`transitions` library (version 0.9.2) for the underlying state machine
engine and on `pytest` (version 8.3.3) for the test suite. No machine
learning, database, or networking components are introduced, which
preserves the deterministic and analytically transparent behaviour
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
