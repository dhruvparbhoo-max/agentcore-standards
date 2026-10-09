# agentcore-completion

Independent completion check. See [the library design](../../docs/design/library.md). Version 0.1.0.

`CompletionVerifier.check` takes a `Claim` and an `Evidence` value. It does not call the proposer. If `proposer_id` equals `verifier_id`, it raises `SamePartyError` instead of accepting.

A claim is rejected when the result is empty, todos are open, a tool errored, a required tool never ran, or a required citation is missing. Acceptance is the empty reason list.
