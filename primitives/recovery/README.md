# agentcore-recovery

Retry budget, circuit breaker, and in-flight cap. See [the library design](../../docs/design/library.md). Version 0.1.0.

`run_with_recovery` calls an operation that returns `AttemptOutcome`. Retryable failures wait with capped exponential backoff. Pass a jitter function; the default is a uniform draw. Fatal outcomes return immediately and do not open the circuit.

The circuit opens after consecutive retryable failures, then stops calling until the cooldown, then allows one half-open probe. `max_attempts` and `max_elapsed_ms` stop a loop that would otherwise keep sleeping. `InFlightGate` stops a second loop when the process is already at the cap. An open circuit or a full gate does not call the operation.
