# Single-instance startup and activation

The per-user `QLockFile` remains authoritative. It is acquired before database
bootstrap and retained until the service container has closed. IPC is only an
activation request; it does not grant database ownership.

The activation receiver is connected before acquisition and bootstrap. Real
page constructors can dispatch Qt events before the main window exists. Requests
during acquisition, data setup, construction or `show()` are therefore retained
and coalesced. They are delivered once after `show()` returns, never against a
half-constructed window. Later requests activate normally; database shutdown
disables activation before releasing the guard.

A lock holder can be scheduled between acquiring ownership and publishing the
local endpoint. The notifier therefore retries only `ServerNotFoundError` and
`ConnectionRefusedError`, before any write, using a fresh socket and a positive
backoff of at most 25 ms. Other connection errors fail immediately. Each failed
attempt is aborted and disconnected. One monotonic 3000 ms application budget
starts at notification entry, covers connection attempts and write draining,
and is never reset by a retry. The existing write-drain cap remains 500 ms;
it is also limited by the remaining overall budget.

This is not a hard wall-clock guarantee. In pinned
[Qt 6.10.2's Windows implementation](https://github.com/qt/qtbase/blob/v6.10.2/src/network/socket/qlocalsocket_win.cpp),
`waitForConnected()` ignores its millisecond argument; a missing pipe fails
immediately, while `connectToServer()` can synchronously wait on a busy pipe.
The application cannot interrupt that native call. It checks the shared deadline
after connecting and before writing, and does not write or retry after exhaustion.

The notifier accepts success only after the complete `activate\n` payload is
accepted and its local write queue drains under one bounded deadline. `flush()`
may already have emptied that queue, and one `waitForBytesWritten()` result means
progress rather than necessarily complete transfer. Success also requires a valid,
connected socket with no observed error: Qt's Windows pipe-error path can discard
a failed writer and leave a zero-length queue. Failure follows the existing
bounded reacquisition/error-message path and must not claim notification success.
Once any write is attempted, including an error or partial acceptance, the
notification is never replayed. If the original owner cancels or fails before
listening, a failed notification still permits only the existing single atomic
reacquisition, never a lock deletion or a second database owner.
Successful submission is not a receiver acknowledgement or proof of foreground
activation; the real onefile race gate separately checks the winner's activation.

The receiver retains only a bounded prefix of that exact frame, including across
multiple reads and the final disconnect. It rejects unrelated, substring-only or
oversized input and emits at most once per connection. An empty compatibility
probe never activates the window.

`test_activation_delivery.py` covers the startup phases, real MainWindow/page
construction with a queued Qt signal, write/drain failures and framing boundaries.
`test_notification_readiness.py` uses explicit transport/clock doubles and real
file locks to cover late readiness, cancellation, legacy endpoints, deadlines,
non-transient errors and no replay after a write. It is not real IPC acceptance.
`test_single_instance.py` retains the real cross-process local-socket tests and
adds a lock-held, deliberately delayed-listen case requiring exactly one received
activation and an actually shown Qt window. Its
failures are not skipped or replaced by these source contracts. The frozen race,
normal close, recovery, strict crash code 77, 18 self-tests and raw 90% coverage
requirements remain unchanged.

The isolated frozen probe records only notification phase, attempt count,
last Qt error code, accepted byte count, elapsed milliseconds and the submission
result. The outer gate records the race loser's actual bootloader exit code before
applying the unchanged zero-exit requirement. These diagnostics do not imply an
inner exit code, receiver acknowledgement or usable window. The strict winner
window/database/activation checks still determine the frozen verdict.

## Visibility observation in the real IPC regression

The delayed-listen child records visibility inside the actual activation
callback, before scheduling normal shutdown. Both its exit decision and the
parent require exactly one receipt and exactly one true visibility observation.
A hidden callback is recorded before its assertion, so a swallowed Qt slot
exception cannot be concealed by a later visible callback. The after-exec
visibility is retained separately as diagnostic information.

The earlier Windows quick run
[38328350140](https://github.com/yung13yubabie/taxops-control-desk/actions/runs/38328350140)
completed the retry, callback and normal child exit but failed its final
post-quit visibility assertion. Qt's
[QApplication Quit handling](https://github.com/qt/qtbase/blob/v6.10.2/src/widgets/kernel/qapplication.cpp#L1560-L1578)
closes windows before leaving the event loop. That failed result is retained;
observing activation before shutdown corrects the test's timing, not the
application or the frozen acceptance policy.
