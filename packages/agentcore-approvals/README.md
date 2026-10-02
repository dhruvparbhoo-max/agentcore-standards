# agentcore-approvals

Single-use approval tokens (DESIGN §2.8, §3.5). Version 0.1.0.

`issue` binds a pending token to the tool name, the argument hash, and the actor. `decide` records approve or reject. The approver must not be the actor. `consume` spends an approved token once, and only when the tool, the hash, and the actor match and `now` is before expiry.

This is the pattern library. The eval pack's `InMemoryHitlGate` remains the eval stand-in.
