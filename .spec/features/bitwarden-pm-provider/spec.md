# Spec: bitwarden-pm-provider

Approved shape: SD page 15007756 (*Shape Intent — Bitwarden Password Manager
Vault-Sync Provider (bwpm://)*), approved by the maintainer on 2026-10-10 —
see `plan.md` → `## Alignment`.

## Behavior

The package registers a **second** remote provider next to `bws`:

- `bwpm` — Bitwarden **Password Manager**, the normal Bitwarden vault, driven
  through the user's already-installed **`bw` CLI as a subprocess**. It adds no
  Python dependency. The `bw` binary is a runtime dependency of this provider
  alone.

**The ambient-session principle.** Sync invents no credential-passing
mechanism. It detects and consumes what the user has already set up: a
logged-in, unlocked `bw` session (`BW_SESSION`). It never logs in, never
prompts for a master password, never handles 2FA, and never persists session
state — the session key never enters the vault, never reaches disk through
this package, never appears on a subprocess command line, and never appears in
an error message.

## The reference grammar

    bwpm://<item>/<field>

- `<item>` is an item **uuid** or an exact item **name**.
- `<field>` is never defaulted. It is one of:
  - `password`, `username`, `totp`, `notes`, `uri` — the built-in slots;
  - `field:<name>` — a custom field by exact name.
- An unknown field is an **error**, not a no-op (`?profile=prod` must not
  resolve quietly).
- The reference carries no query. Anything after a `?` is refused.

## Refusals (each names the state it found)

1. `bw` binary missing → refuse, naming the binary and the provider.
2. Not signed in (`bw status` = `unauthenticated`) → refuse; `bw login` is a
   human step this provider never performs.
3. Session locked (`bw status` = `locked`) → refuse; the human re-unlocks
   (`bw unlock`) and sync re-runs. Nothing enters the vault.
4. Unknown field, unknown item, ambiguous item name, ambiguous custom-field
   name, or an item field with no stored value → refuse, naming the reference
   parts and candidate ids — never a value.

Ambiguity is loud, as in the sibling providers: a wrong pick would be a
*working* run with the wrong credential.

## Field semantics

- `totp` returns the stored **seed/URI** (`login.totp`), never a generated
  code — a code baked into the vault would be a 30-second credential stored
  for days.
- `uri` returns the first URI, which is `bw`'s own convention.
- A `None` or empty stored value refuses rather than writing emptiness into
  the vault.
- Custom fields match by exact name; duplicate field names inside one item are
  an ambiguity error.

## Server selection

The provider invents **no** `BW_*` environment variables. Server selection
stays with the `bw` CLI's own configuration (`bw config server`), which is
what makes this the project's first Vaultwarden-compatible secret source: the
Password Manager API is exactly what Vaultwarden implements.

## Acceptance criteria

- **A1** With an unlocked ambient session, `vault sync` resolves `bwpm://`
  references into the vault; `func run` reads them offline (ADR-016: jobs read
  the vault, never the network).
- **A2** Without `bw`, without a login, or with a locked session, sync fails
  with the specific refusal naming which state it found — and nothing enters
  the vault.
- **A3** The session key and item values are demonstrably absent from error
  messages, from subprocess argument lists, and from any state the provider
  keeps; the vault receives only what `fetch()` returns (structural, as with
  the AWS STS cache).
- **A4** Unit tests drive a fake `bw` shim on `PATH`; no test contacts a real
  vault. An integration module against a live unlocked `bw` (Vaultwarden in
  Docker being the expected backend) exists behind an explicit opt-in and
  skips otherwise.
- **A5** The plugin README documents the runtime dependency, the addressing
  grammar, the session-expiry operational reality (ambient state is less
  durable than a BWS token — sync intermittently needs a human re-unlock),
  and the Vaultwarden compatibility note.
- **A6** `CHANGELOG.md` carries a hand-written `[Unreleased]` → Added entry.
- **A7** `ruff check`, `ruff format --check`, `mypy src/`, `lint-imports`, the
  plugin test suite, and the tests-for-diff selection are green.

## Out of scope

- Logging in, master passwords, 2FA, session creation or persistence.
- New `BW_*` environment variables.
- `bw serve` / an API-server transport (deferred in the shape).
- PyPI publication timing (the package stays deferred from the index like the
  rest of the distribution set until the intentional launch).
