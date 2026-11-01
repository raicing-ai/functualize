# F6 external contracts

## C1. Public job call

The job-facing import and signature are:

```python
from functualize.job import Vault
from functualize.types import Secret

class Vault:
    def read(self, group: str, field: str) -> Secret[str]: ...
```

`Vault` is an injected job capability. A job asks for it by type and calls `read` once with the selected group path or Rise subject address and field name:

```python
def deploy_target(vault: Vault) -> None:
    token: Secret[str] = vault.read("cloudflare_dev.d1.main", "api_token")
    # Pass token to the selected target's trusted work.
```

The method takes no job target, environment selector, source selector, or invocation value. It uses the booted application's active environment and local project vault. The caller receives the canonical public `Secret[str]` wrapper, not a plaintext string or a metadata report. The `Vault` import is available to real jobs on both supported application entry paths.

The capability is the single F6 job call surface. An independent `RunContext` method or free function is not part of this contract. If Plan finds that the capability cannot be wired without violating a repository boundary, return to Specify and reconfirm a revised signature.

## C2. Missing and unreadable entries

`Vault.read` has three observable outcomes:

| Situation | Caller observes | Further lookup |
| --- | --- | --- |
| First existing group candidate is readable | `Secret[str]` | Stops at that candidate. |
| No candidate exists in active or shared tier, including no vault file | `VaultEntryMissingError` | No fallback to another source. |
| First existing candidate cannot be opened | Existing `VaultEntryUnreadableError` for unavailable/wrong key, or existing `VaultDecryptionError` for authentication failure | Stops at that candidate; no ancestor or shared fallback. |

`VaultEntryMissingError` is a new public subclass of `VaultError`, importable from `functualize.app.vault`. It names the requested group and field without including a secret value. The error means absence across the complete candidate sequence, not “the exact address was absent.” It is distinct from a stored-entry read failure and is suitable for an explicit caller decision, such as declining to operate on that target.

`VaultEntryUnreadableError` and `VaultDecryptionError` remain the existing vault failures, exported from `functualize.app.vault` for callers of this public read. Their messages and diagnostics contain no plaintext. Malformed arguments are input errors rather than missing entries; the existing group address and field grammar applies.

This dedicated error is specific to the **explicit public read**. Ordinary group-option and job-config resolution retains its existing behavior when a vault entry is absent: it may continue through its configured lower-priority sources. F6 must not turn that existing config-chain miss into a hard failure.

## C3. Candidate and secrecy invariants

For `Vault.read(group, field)`, candidate identities are equivalent to the existing `VaultIdentity.lookup_candidates("group", group, field, active_environment)` sequence: all active-environment addresses from exact to nearest ancestors, followed by all shared addresses in the same order. The first stored identity is authoritative even when unreadable. Job-scope entries and other named environments are excluded.

The returned value is wrapped before it crosses the public boundary. String and representation rendering remain masked. Neither the method nor its errors, stdout, stderr, logs, or diagnostics reveal the secret. `vault inspect` and `vault list` continue to expose metadata only. No provider fetch occurs in a job; `vault sync` remains the remote operation.
