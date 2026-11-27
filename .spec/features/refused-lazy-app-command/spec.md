# Refused lazy app commands

## Status

Specified for this branch; the warm app-script behavior is not implemented yet.

## Behavior

A job whose parameter is refused during discovery remains listed. Calling it through a `FunctualizeApp` script reports the stored refusal before Click interprets supplied arguments. The answer names the job and parameter, includes the remedy, has one `Error:` line, contains no traceback, and exits 2. This applies on cold and warm boots to bare calls, unknown options, extra positionals, workflow flags, and flags after a grouped job. `--help` remains available and exits 0. No refused job runs.

## Acceptance

- An app-script subprocess test primes a distinct warm cache with `--help` for each argument shape, and confirms the lazy command builder is reached on warm calls but not cold calls.
- The same test checks the exact refusal line on cold and warm calls, including workflow and group arguments.
- The existing `func` refusal tests and the parameter-contract probe surface remain green.

## Boundary

The app-script CLI adapter is the changed surface. `func` remains the parity reference; independent workflow/info commands and non-CLI adapters are outside this change.
