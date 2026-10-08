# agentcore-context

Prompt assembly and the state bar (DESIGN §2.8). Version 0.1.0.

`StateBar.render` prints open-todo, tool, and error counts and the circuit state. Long todo lists keep the counts and record how many todos were omitted.

`assemble_context` places system text, the state bar, and the user turn first. Tool results are dropped first when the budget is exceeded, then older memory, then retrievals. Those three pinned parts are never dropped; if they alone exceed the budget, assembly raises. Memory lines must be built with `screened=True`.

`token_estimate` uses the length heuristic. `estimate_source` is `length-heuristic`. That is not a model bill.
