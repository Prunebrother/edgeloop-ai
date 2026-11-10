# Experimental software for adults

No physical safety certification or new live-hardware validation is claimed. Heart rate is an imperfect signal and AI interpretations may be false. Neither dialogue nor a successful simulation establishes safe physical operation.

The original EdgeLoop engine is the sole hardware authority. With **AI Settings Control** enabled (off by default), a companion may request a limited set of session-setting changes: play style, game, endgame, the orgasm toggle, intensity inside user-set limits, and pause/stop. Every request passes a local gate that enforces an allowlist, the user's limits, rate limits, a fresh heart-rate signal and device readiness, then goes through the same engine path as manual controls. The AI can never start or resume a session, stream motion, change heart-rate limits, select devices or bypass watchdogs, disconnect protection or emergency stop. Emergency stop revokes AI control for the session. Character prompt text cannot widen these permissions. With AI Settings Control off, the observer only consumes observations and outputs dialogue/presentation. All engine, hardware-driver and manual-control source files are preserved byte-for-byte from the working snapshot.

Use EdgeLoop's manual Stop control to end a session. Existing pause/stop, device disconnect and emergency behavior remain available. Know the physical device's own stop/disconnect mechanism. Stopping AI services does not stop hardware or close the browser. Never rely on the companion to detect a fault or stop a device.

Supported source integrations are standard BLE heart-rate service, Handy, Buttplug/Intiface, TCode and VacuGlide. Presence in source does not establish tested compatibility with a particular model, firmware, browser or operating system. First-time testing should use the simulator and mocked-device fixture. Public observer/Ollama exposure, direct AI hardware control, unattended physical operation and bypassed safeguards are unsupported.

Inference remains `think:false`. Scheduling and context budgets remain bounded. Experimental idle Director initiative is off by default. Ordinary operating defaults have not been changed for release convenience. Character prompt text cannot grant hardware authority.

Changes affecting hardware or safety must receive focused review and regression coverage before merge; see CONTRIBUTING.md. Do not interpret model output as medical advice or as verified perception of a user's body or mental state.
