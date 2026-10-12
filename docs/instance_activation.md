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

The notifier accepts success only after the complete `activate\n` payload is
accepted and its local write queue drains under one bounded deadline. `flush()`
may already have emptied that queue, and one `waitForBytesWritten()` result means
progress rather than necessarily complete transfer. Success also requires a valid,
connected socket with no observed error: Qt's Windows pipe-error path can discard
a failed writer and leave a zero-length queue. Failure follows the existing
bounded reacquisition/error-message path and must not claim notification success.
Successful submission is not a receiver acknowledgement or proof of foreground
activation; the real onefile race gate separately checks the winner's activation.

The receiver retains only a bounded prefix of that exact frame, including across
multiple reads and the final disconnect. It rejects unrelated, substring-only or
oversized input and emits at most once per connection. An empty compatibility
probe never activates the window.

`test_activation_delivery.py` covers the startup phases, real MainWindow/page
construction with a queued Qt signal, write/drain failures and framing boundaries.
`test_single_instance.py` remains the real cross-process local-socket test; its
failures are not skipped or replaced by these source contracts. The frozen race,
normal close, recovery, strict crash code 77, 18 self-tests and raw 90% coverage
requirements remain unchanged.
