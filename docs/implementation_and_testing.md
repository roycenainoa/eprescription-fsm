# Implementation

The implementation translates the formal deterministic finite automaton defined in the
preceding section into a Python package that extends the Phase 2 prototype with four
production-oriented capabilities: a SQLite persistence layer, an automated expiry scheduler,
an HL7 FHIR interoperability adapter, and a reentrant concurrency lock on the state mutation
path. The complete source code is available in the public GitHub repository. The project
continues to depend on the `transitions` library (version 0.9.2) for the underlying state
machine engine and on `pytest` (version 8.3.3) for the test suite. Phase 3 introduces
SQLAlchemy (version 2.0) as its only new dependency, which preserves the deterministic and
analytically transparent character of the model.

## Module Structure

The package is organised into six modules inside the `src` directory. The `exceptions` module
defines the typed exception hierarchy. The `prescription` module exposes the `Prescription`
class and its concurrency guard. The `validator` module provides the sequence acceptor
described in the Sequence Validator section below. The `storage` module implements the
SQLAlchemy persistence repository. The `scheduler` module provides the threading-based expiry
scheduler. The `fhir` module implements the HL7 FHIR MedicationRequest parsing adapter. A
corresponding `tests` directory contains six pytest modules: `test_prescription`,
`test_validator`, `test_storage`, `test_scheduler`, `test_fhir`, and `test_concurrency`. The
Phase 3 total is 76 cases.

## The Prescription Class

The `Prescription` class is the core artefact of the implementation. On construction, it
instantiates a `transitions.Machine` bound to itself, passes the six declared states, and
registers the transition function as a list of dictionaries. Each dictionary maps an event
trigger to its permitted source states and a single destination state, which directly mirrors
the mathematical transition function defined in the formal model. The initial state is set to
`drafted`. The constructor argument `auto_transitions=False` is set so that the library does
not synthesise shortcut triggers, which would otherwise introduce paths that violate the
formal model. The argument `ignore_invalid_triggers=False` ensures that any unauthorised event
raises a `MachineError` rather than silently failing. A reentrant lock (`threading.RLock`) is
created at construction time to serialise concurrent access to the state mutation path.

```python
STATES = [
    "drafted", "signed", "transmitted",
    "dispensed", "expired", "cancelled",
]

TRANSITIONS = [
    {"trigger": "sign",     "source": "drafted",                     "dest": "signed"},
    {"trigger": "transmit", "source": "signed",                      "dest": "transmitted"},
    {"trigger": "dispense", "source": "transmitted",                  "dest": "dispensed"},
    {"trigger": "expire",   "source": ["signed", "transmitted"],      "dest": "expired"},
    {"trigger": "cancel",   "source": ["drafted", "signed", "transmitted"],
                                                                      "dest": "cancelled"},
]

class Prescription:
    def __init__(self, identifier=None):
        self.identifier = identifier
        self.history = []
        self._lock = threading.RLock()
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

Every successful transition triggers an `after_state_change` callback named
`_record_transition`, which appends the new state to an internal `history` list. The history
acts as a deterministic audit trail. Because the callback fires only after the library has
committed a transition, rejected events leave the history untouched. This guarantee is
verified explicitly by the test `test_rejected_event_does_not_mutate_state`.

## Guard Logic and Exception Handling

The default behaviour of the `transitions` library is to raise a generic `MachineError` for
any unauthorised input. While sufficient for control flow, this exception type does not
distinguish between two semantically different rejection reasons that matter for clinical
auditing. The first case is an event that is simply undefined for the active state, such as
attempting to dispense a drafted prescription. The second case is an event dispatched against
a prescription that has already entered a terminal state. The implementation therefore exposes
a single dispatch method, `trigger_event`, that wraps the library call and routes each class
of failure to a dedicated typed exception. The method also acquires the reentrant lock before
reading or mutating the state, which prevents two threads from interleaving a state check with
a state write.

```python
def trigger_event(self, event_name):
    with self._lock:
        if self.state in TERMINAL_STATES:
            raise TerminalStateError(self.state, event_name)
        try:
            self.trigger(event_name)
        except (MachineError, AttributeError) as exc:
            raise InvalidTransitionError(self.state, event_name) from exc
        return self.state
```

Terminal states are pre-checked before any call into the library, which guarantees that the
three accept states (`dispensed`, `expired`, `cancelled`) possess no outbound transitions.
The `TerminalStateError` and `InvalidTransitionError` exceptions both store the offending
state and event name as attributes, which allows downstream auditing code to generate
structured log records without parsing exception messages.

## Sequence Validator

The `validate_sequence` function in the `validator` module realises the formal definition of
language acceptance from automata theory. Given a list of event names, it instantiates a fresh
`Prescription` and dispatches each event in order. The first event that raises either exception
halts processing, and the function returns a `ValidationResult` dataclass that captures the
accepted flag, the final state, the prefix of events consumed before rejection, the offending
event, and a human-readable rejection reason. An empty sequence is accepted with a final state
of `drafted`, which is consistent with the convention that the empty input leaves the automaton
in its initial state.

## Persistence Layer

Prescription state is persisted to a SQLite database via SQLAlchemy ORM. The `storage` module
defines a `PrescriptionRecord` table with columns for the prescription identifier, the current
state string, the history serialised as a JSON string, and two UTC timestamps for the creation
and most recent update. Serialising the history list as JSON keeps the schema flat and portable
without requiring a separate audit table.

```python
class PrescriptionRecord(Base):
    __tablename__ = "prescriptions"

    id         = Column(Integer, primary_key=True)
    identifier = Column(String, unique=True, nullable=False, index=True)
    state      = Column(String, nullable=False)
    history    = Column(String, nullable=False, default="[]")
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)
```

The `PrescriptionRepository` class wraps a SQLAlchemy session and exposes two methods. The
`save` method inserts a new record or updates an existing one using the identifier as the
natural key. The `load` method reconstructs a `Prescription` instance by setting the machine
to the persisted state string and restoring the history list from the JSON column; the
reconstructed instance accepts further transitions exactly like a fresh instance. This design
separates the FSM logic from the persistence concern so that neither the `Prescription` class
nor the `transitions` library needs to be aware of the backing store.

A helper function, `create_engine_and_session`, builds a SQLAlchemy engine and session factory
from a URL string. When the URL refers to an in-memory SQLite database, the caller can opt in
to a static connection pool so that multiple sessions within the same process share a single
database without requiring a file. This option supports tests that simulate a process restart
against an in-memory store.

## Automated Expiry Scheduler

The `ExpiryScheduler` class dispatches the `expire` event after a caller-specified delay by
wrapping `threading.Timer`. The timer thread is marked as a daemon so that a forgotten
scheduler cannot hold the Python process open after the main thread exits. The class enforces
a positive delay at construction time and raises `ValueError` for zero or negative values.

The scheduler owns at most one active timer at a time. Calling `start` while a timer is
already pending cancels the earlier timer before scheduling a fresh one, which makes it safe
to call from event handlers that re-arm expiry on each lifecycle change. The `cancel` method
stops any pending timer and is safe to call multiple times. When the timer fires, an internal
`_fire` method calls `trigger_event("expire")` on the prescription. If the prescription has
already moved to a terminal state or out of an expiry-eligible state between scheduling and
firing, the resulting `InvalidTransitionError` or `TerminalStateError` is swallowed silently,
because these outcomes represent expected races rather than programming errors.

## FHIR Integration Adapter

The `fhir` module provides a `prescription_from_fhir` function that constructs a
`Prescription` from an HL7 FHIR R4 MedicationRequest payload represented as a Python
dictionary. The function verifies the resource type, extracts the prescription identifier,
and maps the FHIR `status` field to one of the six declared FSM states using a fixed
dictionary. Clinical data exchange standards define a canonical set of status codes for the
MedicationRequest resource, and aligning these codes with the FSM state set enables
prescriptions to be imported from an external FHIR endpoint without a manual transformation
step (Saripalle et al., 2019).

```python
FHIR_STATUS_TO_FSM_STATE = {
    "draft":     "drafted",
    "active":    "signed",
    "completed": "dispensed",
    "cancelled": "cancelled",
    "stopped":   "cancelled",
    "ended":     "expired",
}
```

The mapping covers the subset of FHIR status values that correspond directly to states in the
model. Status values outside this set, such as `entered-in-error`, are rejected with a
`FHIRParseError` to prevent the FSM from being initialised in an undefined configuration.
Interoperability frameworks that surface prescriptions as FHIR resources can invoke this
adapter to produce a live FSM instance that continues the prescription lifecycle from the
imported state onward (Das & Hussey, 2023). Identifier extraction follows the FHIR convention
of preferring the `identifier` array over the top-level `id` field, which reflects the
practice of carrying business identifiers as structured objects rather than bare strings.

## Verification

Correctness is established through 76 pytest cases distributed across six test modules. The
suite covers the standard workflow, terminal state enforcement, guard logic, the sequence
acceptor, FHIR status mapping and parse error handling, scheduler firing and cancellation,
persistence round trips and process-restart recovery, concurrent transition races, and stress
tests under thousands of rapid illegal events. The full suite executes in under two seconds,
which makes it suitable for inclusion in a continuous integration pipeline. The testing
approach and detailed results are presented in the Testing section.


# Testing

The implementation is verified through a structured suite of unit tests written with the
pytest framework. The deterministic nature of the finite state machine makes it well suited to
unit-level verification, because every transition produces an observable result that depends
only on the current state and the dispatched event. Phase 3 extends the Phase 2 suite of 38
cases with 38 new cases covering the persistence layer, the automated scheduler, the FHIR
adapter, and concurrent multi-threaded access. The combined 76-case suite is organised so that
each category maps back to a formal property or a Phase 3 capability.

## Testing Methodology

Pytest was selected for the suite because it provides a minimal declarative test syntax,
native support for parametrised cases, and clear failure reporting without requiring an
inheritance hierarchy. Tests are written in a black-box style: each case interacts with the
model exclusively through its public interface and observes the resulting state, the audit
history, and any raised exceptions. This style ensures that the tests document expected
behaviour rather than implementation details, and remain valid if the internal callback
mechanism of the `transitions` library is later adjusted.

Phase 3 tests apply the same black-box principle to the new modules. Persistence tests
interact only through `PrescriptionRepository.save` and `PrescriptionRepository.load`.
Scheduler tests observe state changes on the prescription object after a configurable short
delay and do not inspect internal timer state directly. FHIR tests pass dictionary payloads to
`prescription_from_fhir` and assert on the returned prescription or the raised
`FHIRParseError`. Concurrency and stress tests use `concurrent.futures.ThreadPoolExecutor` to
spawn competing threads and then assert on aggregated success and failure counts after the
pool is exhausted.

## Test Categories

### Phase 2: Core FSM (38 cases)

| Category                     | Tests | Property verified                                             |
|------------------------------|------:|---------------------------------------------------------------|
| Initial state correctness    |     3 | The prescription starts in `drafted` with empty history       |
| Standard workflow            |     5 | drafted to signed to transmitted to dispensed                 |
| Expiry guard                 |     3 | `expire` is valid only from `signed` or `transmitted`         |
| Cancellation guard           |     3 | `cancel` is valid from any pre-terminal state                 |
| Terminal state enforcement   |     6 | No event mutates a terminal state                             |
| Illegal transition rejection |     6 | Undefined events raise `InvalidTransitionError`               |
| Exception payload integrity  |     2 | Exceptions carry the offending state and event name           |
| Sequence validator           |    10 | Acceptor reproduces the FSM acceptance behaviour              |

### Phase 3: Extended capabilities (38 cases)

| Category                     | Tests | Property verified                                                      |
|------------------------------|------:|------------------------------------------------------------------------|
| FHIR status mapping          |     6 | Each mapped FHIR status yields the correct FSM state                   |
| FHIR identifier extraction   |     3 | Identifier list takes precedence; top-level `id` is a fallback         |
| FHIR parse error handling    |     5 | Malformed, missing, or unmapped fields raise `FHIRParseError`          |
| FHIR functional integration  |     2 | FHIR-loaded prescriptions continue the lifecycle correctly             |
| Scheduler fires              |     2 | Timer dispatches `expire` from `signed` and `transmitted`              |
| Scheduler cancellation       |     4 | Cancel stops the timer; terminal-state fires are swallowed silently    |
| Scheduler validation         |     3 | Zero or negative delays are rejected; re-arm replaces the old timer    |
| Persistence save and load    |     6 | Round trips preserve state and history; further transitions succeed    |
| Persistence recovery         |     1 | A new session against a file database recovers the persisted state     |
| Concurrent transitions       |     3 | Exactly one thread wins each race; all others receive typed errors     |
| Stress invalid transitions   |     3 | Thousands of illegal events leave state and history unchanged          |

Several cases are parametrised. The terminal state category uses pytest parametrisation to
dispatch all five defined events against each of the three terminal states, producing fifteen
logical assertions from a single test function. This pattern compacts the test file while
still covering every illegal combination.

## Concurrency Tests

Three concurrency tests verify that the reentrant lock in `trigger_event` serialises competing
dispatches correctly. Each test constructs a `Prescription` and submits worker functions to a
`ThreadPoolExecutor`. The assertions confirm outcomes that are reachable only if the lock
prevents interleaving.

`test_only_one_thread_can_sign` submits ten threads that each attempt to call `sign` on a
freshly drafted prescription. Because `sign` is legal only from `drafted` and the machine
transitions to `signed` on the first successful call, every subsequent attempt observes the
post-sign state and must raise `InvalidTransitionError`. The test asserts that exactly one
thread recorded a success and that the history contains exactly one entry.

`test_full_lifecycle_under_contention` runs one thread that advances the prescription through
the full lifecycle (sign, transmit, dispense) while three other threads each attempt the
`expire` event 50 times. The final assertions confirm that the state is `dispensed` and the
history contains exactly the three legal transitions, regardless of the interleaving of
illegal attempts.

`test_concurrent_cancels_only_commit_once` races eight threads trying to cancel the same
drafted prescription. Exactly one wins and receives the `cancelled` state; the remaining seven
observe the terminal state and must raise `TerminalStateError`. The test asserts the exact
success and failure counts.

## Stress Tests

Three stress tests verify that the FSM remains coherent under a high volume of rapid illegal
events and that no exception escapes the typed hierarchy.

`test_rapid_invalid_transitions_do_not_mutate_state` dispatches 2 000 consecutive attempts of
the `dispense` event against a prescription in the `signed` state, which does not permit
`dispense`. Every attempt must raise `InvalidTransitionError`. The test counts errors and
confirms that the state and history are identical to their values before the loop.

`test_rapid_events_against_terminal_state` advances a prescription to `dispensed` and then
cycles through all five defined events 500 times each, for a total of 2 500 calls. Every call
must raise `TerminalStateError`. The test asserts the exact error count and confirms that the
state has not changed.

`test_unknown_events_under_stress` signs a prescription and then dispatches 1 000 event names
that are not part of the declared alphabet. Each must raise `InvalidTransitionError`, and the
state must remain `signed` throughout.

## Scheduler, Storage, and FHIR Tests

Scheduler tests use a 50-millisecond delay and poll the prescription state at 10-millisecond
intervals with a 2-second deadline. This approach avoids fixed sleeps and remains stable under
varying system load. The cancellation tests use a 500-millisecond delay to provide a window in
which the prescription can be advanced to a terminal state or the timer can be cancelled before
it fires.

Storage tests use an in-memory SQLite database with a static connection pool, which ensures
that the save session and the load session share the same data without requiring a file. A
dedicated recovery test writes to a temporary file-backed database, disposes of the session
factory, opens a new session factory against the same file, and asserts that the loaded
prescription matches the saved state. This simulates a process restart against a durable
backing store.

FHIR tests use a minimal but structurally valid MedicationRequest fixture and vary only the
fields under test. Parse error tests confirm that each class of malformed input raises
`FHIRParseError` before any `Prescription` object is created. Integration tests confirm that a
`Prescription` returned by the adapter can continue its lifecycle through subsequent
`trigger_event` calls.

## Results

The full 76-case suite passes in 1.72 seconds on a standard laptop. Because the tests do not
depend on the network, the file system, or a wall clock (except for the scheduler polling
tests, which use monotonic time), the runtime is stable across executions and the suite is
suitable for inclusion in a continuous integration pipeline. A reviewer can reproduce the
result with a single command after installing the dependencies:

```bash
pytest -v
```

The verbose flag prints the name of every test case and its outcome, which makes the
per-category coverage immediately visible in the console output.

## Limitations

The suite establishes correctness of the transition function, the persistence round trip, the
scheduler dispatch, the FHIR mapping, and the concurrency guard within a single process. It
does not address several concerns that would arise in a distributed deployment. The SQLite
backing store is single-node; concurrent writes from multiple application processes are not
tested, because SQLite serialises all writes through a file-level lock, which is a weaker
guarantee than row-level locking available in client-server databases. Full HL7 FHIR
conformance validation, including profile binding, terminology server lookups, and
cross-resource reference resolution, is out of scope and would require a dedicated FHIR
validation library. Cryptographic verification of the prescriber identity at the `sign`
transition is not implemented. These limitations are intentional given the analytical scope
defined in the Introduction and are discussed further in the Conclusion.


# Conclusion

This project set out to model the electronic prescription lifecycle as a deterministic finite
automaton and to verify the model through a structured test suite. Phase 2 established the
formal foundations: a six-state machine with a strict transition function, a typed exception
hierarchy, and a sequence acceptor that mirrors the mathematical definition of language
recognition. Phase 3 extended the prototype with four capabilities that move it closer to the
requirements of a production prescription management system.

The persistence layer introduced in Phase 3 allows a prescription instance to be saved to and
recovered from a SQLite database, which means that a process restart no longer discards
in-flight prescription state. The separation of the `PrescriptionRepository` from the
`Prescription` class ensures that the FSM logic remains free of database concerns and that
the backing store can be replaced without modifying the model.

The automated expiry scheduler delivers the `expire` event after a caller-specified delay
without requiring any polling loop in application code. The timer thread runs as a daemon,
which prevents it from blocking process shutdown. When a prescription reaches a terminal state
before the timer fires, the rejected event is swallowed silently, preventing spurious errors
in the common case where a prescription is dispensed or cancelled before its expiry window
closes.

The FHIR integration adapter enables prescriptions to be imported from an external HL7 FHIR
R4 endpoint and represented as live FSM instances without a manual transformation step. The
adoption of FHIR as a common data exchange standard in healthcare information systems makes
this adapter a meaningful integration point for scenarios in which prescriptions originate in
a clinical order management system and are tracked through dispensing in a pharmacy management
system (Das & Hussey, 2023; Saripalle et al., 2019). The adapter explicitly rejects status
values outside the mapping to prevent the model from being initialised in an undefined
configuration, which preserves the formal guarantee that every reachable state is a member of
the declared state set.

The concurrency guard, implemented as a reentrant lock around the `trigger_event` method,
ensures that simultaneous calls from multiple threads cannot produce a corrupted audit history.
The test suite demonstrates that exactly one thread wins each race across three independent
contention scenarios and that all others receive well-typed exceptions.

Several limitations remain. The SQLite backing store is single-node, which means that the
persistence layer does not support concurrent writes from multiple application processes. A
distributed prescription management environment would require a client-server database with
row-level locking and a distributed lock on the FSM mutation path. Electronic prescription
systems that operate across healthcare organisations also face regulatory requirements around
prescriber authentication; the `sign` transition in this model records a state change but does
not verify a cryptographic signature, which would be a prerequisite for legal validity in most
jurisdictions (Lundhaug et al., 2025). Full HL7 FHIR conformance validation, including
profile binding and terminology server lookups, is out of scope for the current adapter. These
limitations represent concrete directions for future work rather than fundamental constraints
of the FSM modelling approach.

The deterministic finite automaton remains the appropriate abstraction for formalising the
prescription lifecycle. Its analytical transparency allows the transition function, the accept
states, and the exception semantics to be verified through a suite of 76 automated tests in
under two seconds. The Phase 3 additions demonstrate that the core model can be extended with
persistence, scheduling, interoperability, and concurrency without modifying the fundamental
transition logic or relaxing any of the invariants established in Phase 2.
