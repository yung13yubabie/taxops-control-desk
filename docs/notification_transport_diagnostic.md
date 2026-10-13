# Windows notification transport diagnosis

Run the fixed source checkout in the pinned release/CI Python environment:

```text
python -m build_tools.notification_transport_probe --output artifacts/notification-transport
```

The output directory must be new. This is a source Qt/PySide 6.10.2 transport
experiment using `QCoreApplication`, real local sockets and the production
`SingleInstanceGuard.notify_existing()`. It does not run the frozen executable
or its replaced official VC runtime, and is not window or application acceptance.
The production frame, connection attempts, deadlines and return value are unchanged.

Five independent synthetic receiver/sender pairs compare:

- `immediate`: a listening receiver dispatches its normal Qt events.
- `delayed_accept`: the server is listening but has not accepted the connection;
  after the sender's actual write returns, acceptance is held for 800 ms.
- `accepted_no_dispatch`: a real connection is accepted and the native Qt reader
  is started before writing is allowed; Qt event dispatch is then held for 800 ms.
- `never_accept`: no connection is accepted before the sender finishes.
- `peer_close`: the real listener closes after connection and before writing.

Handshakes establish ordering. The 800 ms hold is an experimental control longer
than the existing 500 ms drain cap, not a proposed product timeout. Only cases
that require a handshake create connect/write markers; `immediate` and
`never_accept` add no marker I/O inside notification. Necessary handshake I/O
and waits count toward the unchanged production 3000 ms budget. They deliberately
perturb timing, as does the smaller scalar tracing overhead; this is not a
timing-identical uninstrumented run. Marker I/O is outside
`waitForBytesWritten`; the trace records method boundaries, numeric return
values, pending bytes, state/error enums, validity, observed error events, cumulative
`bytesWritten` signals and monotonic timing. A separate terminal snapshot is taken
before `disconnectFromServer`. No socket is retained by instrumentation, no Qt
events are pumped by it, and no payload, server name, user path or environment is
included in these scalar reports. OS completion, Qt queue consumption, receiver
activation and visible-window readiness remain distinct facts.

`diagnostic_complete` means both diagnostic actors returned and reported their
actual result, including `notify_result: false` for negative controls. It never
means a successful notification or a repaired application. Actor, handshake and
process failures make the overall command nonzero. Owned Windows process-tree
cleanup is bounded and remains failure evidence, not normal-exit proof.

Retain only `notification-transport.json`, each case's `sender.json`,
`receiver.json`, `sender-process.log`, `receiver-process.log`, and, if produced,
`owned-process-cleanup.json`. Do not upload synthetic profile folders, locks or
handshake markers. Preserve the original failed frozen evidence separately;
only a fresh strict frozen run can establish the application outcome.

The process `.log` files contain only output byte counts and SHA-256 digests,
not raw stdout/stderr. Raw Qt or Python diagnostics can contain absolute runner
paths even with synthetic data, so they remain in transient private files and
are not uploaded. Cleanup receipts likewise whitelist only status/type and
numeric or Boolean fields; the raw cleanup helper receipt stays under the
excluded synthetic profile.

The parent verifies each actor's role, case, Qt/PySide/Python versions, application type,
actual loaded source hash and probe hash before marking that case complete.
Connection handshakes require a connected, valid real socket; delayed-write holds
require an actual nine-byte acceptance result. Failed prerequisites remain failed
diagnostics. If both owned actors need cleanup, their role-tagged sanitized
receipts are retained together in the same cleanup artifact.
