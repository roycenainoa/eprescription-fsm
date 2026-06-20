# Reflective Abstract: Phase 3 Development

## Introduction to the Process

Phase 2 of this project delivered a theoretically correct deterministic finite automaton
modelling the electronic prescription lifecycle, verified by 38 automated tests. The model
operated entirely in memory, however, and could not survive a process restart, respond to
elapsed time, or handle concurrent access. Phase 3 addressed the gap between a formal
specification and an operational engineering artefact.

## Addressing Tutor Feedback: The Engineering Evolution

Feedback after Phase 2 identified four gaps between the theoretical model and a clinically
operable system.

The first gap was persistence. I introduced a SQLAlchemy ORM layer backed by SQLite,
implementing persistence as a repository class separate from the Prescription class. This kept
the FSM logic free of database concerns and made the backing store replaceable without
modifying the transition logic.

The second gap was automated expiry. I implemented an ExpiryScheduler wrapping
threading.Timer that dispatches the expire event after a configurable delay. A deliberate
decision was to swallow InvalidTransitionError and TerminalStateError silently in the timer
callback, because the most common production outcome is that a prescription is already
dispensed or cancelled before the expiry window closes; surfacing that race as an error would
produce noise rather than signal.

The third gap was interoperability. I built a prescription_from_fhir adapter that maps the
HL7 FHIR R4 MedicationRequest status field to one of the six FSM states via a fixed lookup
table, rejecting any unmapped value to prevent the FSM from being initialised in an undefined
configuration.

The fourth gap was the test suite. I introduced a concurrency suite using ThreadPoolExecutor
to race multiple threads against a shared prescription instance, and a stress suite
dispatching thousands of illegal events to confirm that the audit history remained uncorrupted
throughout.

## Challenges Faced

The central architectural challenge was maintaining determinism while introducing asynchronous
concerns. A threading.Timer fires on a background thread, so the expire event can arrive at
any point in the lifecycle. This required a reentrant lock, threading.RLock, around
trigger_event. A plain Lock would have deadlocked because trigger_event invokes the
transitions library internally, which fires the after_state_change callback before returning;
both must occur within a single acquisition.

Persistence recovery posed a subtler problem. Reconstructing a Prescription required calling
set_state directly, bypassing the normal transition sequence; the restored audit history
becomes the sole evidence of prior state changes, making serialisation correctness critical.

## Lessons Learned

This project reinforced that formal methods are a prerequisite for engineering effort rather
than an alternative to it. The transition function defined in Phase 2 made every Phase 3
extension easier to reason about: expiry-eligible states were enumerable, reachable FHIR
import states were explicit, and lock invariants were derivable from the model. Separation of
concerns at the module boundary meant the Phase 2 suite required no modification for Phase 3,
and each new module is covered by its own isolated tests.

## Future Considerations

Two changes would improve a future iteration. First, a client-server database rather than
SQLite from the outset: a single-process file store cannot support the row-level locking
required for multi-process deployments, and this constraint should be architectural rather
than a listed limitation. Second, cryptographic signing integrated at the sign transition from
the beginning rather than deferred: a state labelled signed implicitly claims prescriber
authentication, and leaving that claim unverified creates the kind of assumption that produces
exploitable gaps in production clinical systems.
