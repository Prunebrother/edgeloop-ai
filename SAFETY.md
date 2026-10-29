# Experimental software for adults

No physical safety certification or new live-hardware validation is claimed. Heart rate is an imperfect signal and AI interpretations may be false. Neither dialogue nor a successful simulation establishes safe physical operation.

The original EdgeLoop engine is the sole hardware authority. The observer consumes observations and outputs dialogue/presentation. It must never send hardware commands, change physiological limits, or bypass device readiness, watchdogs, disconnect protection or session rules. All engine, hardware-driver and manual-control source files are preserved byte-for-byte from the working snapshot.

Use EdgeLoop's manual Stop control to end a session. Existing pause/stop, device disconnect and emergency behavior remain available. Know the physical device's own stop/disconnect mechanism. Stopping AI services does not stop hardware or close the browser. Never rely on the companion to detect a fault or stop a device.

Supported source integrations are standard BLE heart-rate service, Handy, Buttplug/Intiface, TCode and VacuGlide. Presence in source does not establish tested compatibility with a particular model, firmware, browser or operating system. First-time testing should use the simulator and mocked-device fixture. Public observer/Ollama exposure, AI hardware control, unattended physical operation and bypassed safeguards are unsupported.

Inference remains `think:false`. Scheduling and context budgets remain bounded. Experimental idle Director initiative is off by default. Ordinary operating defaults have not been changed for release convenience. Character prompt text cannot grant hardware authority.

Changes affecting hardware or safety must receive focused review and regression coverage before merge; see CONTRIBUTING.md. Do not interpret model output as medical advice or as verified perception of a user's body or mental state.
