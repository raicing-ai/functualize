"""A secret a job asks for by an address it only learns while it runs.

A config field reaches a job because the job declared it. This job cannot work
that way: which target it publishes to is decided per run, and the address it
reads is *deeper* than any group it declares. It asks the injected ``Vault`` for
that target's entry instead, and passes the wrapper on to the one function that
needs the value. Nothing here logs the credential, and a ``Secret`` refuses to
render it if anything tried.

Three things make the read work, and none of them is a declaration on `publish`:

**The group declaration.** ``CloudflareD1Options`` is what makes an entry at
``cloudflare.d1`` storable at all — the vault only accepts a field the group
declares ``Secret[str]``, so `func builtin vault put --group cloudflare.d1
--field api_token` is refused without it. Where that class may live depends on
the provider that scans the tree. A cached provider keeps a declaration that
sits alone in a job-free ``jobs/deploy/_group.py``: it caches group options
before its no-jobs early return (``_discovery/sync.py``). The eager direct
sources this lab boots — ``JobSources(..., lazy=False)`` — do not, and find a
group only in a module that also holds a job injecting its options.
``group_status`` is that job here. `publish` injects nothing, because a job
that declares the group's options has them resolved and injected before its
body runs (``_engine/executor.py``), which is the one thing an explicit read
must not depend on.

**The candidate walk.** ``vault.read`` asks for the address it is given, then
that address's nearest ancestors. One credential at ``cloudflare.d1`` therefore
answers for every target beneath it, which is why a job that does not know its
target in advance can still serve all of them.

**The three failures are not the same.** An address with nothing stored — exact
group or any ancestor — raises ``VaultEntryMissingError``, which a job can
reasonably survive: the target is skipped. An entry that is *stored* and cannot
be opened with the available key raises ``VaultEntryUnreadableError``, which
this job deliberately does not catch: silently skipping a target whose
credential exists but will not decrypt would hide a broken key behind an empty
deploy. And an entry that will not decrypt raises ``VaultDecryptionError`` —
the stored value did not authenticate under the key in use, which on its own
says nothing about which of the two is at fault — and nothing here catches that
either. A store written before the key check row existed cannot even say
whether the key is the right one, so the repair there is to retry with the key
that wrote it; in this example the check row already names that key and the
bytes are damaged on purpose, so no key repairs them. Either way the run must
not read as a clean deploy.
"""

from pydantic import BaseModel, Field

from functualize.app.vault import VaultEntryMissingError
from functualize.job import (  # noqa: TC001 -- the engine reads these at run time
    GroupOptions,
    Log,
    Vault,
)
from functualize.job.decorators import job
from functualize.types import Secret


class CloudflareD1Options(GroupOptions, group="cloudflare.d1"):
    """The credential every target under it inherits, and the group it is stored for."""

    api_token: Secret[str] = Field(default="", description="Cloudflare API token")


class PublishConfig(BaseModel):
    target: str = Field(
        default="cloudflare.d1.main",
        description="Subject address of the target, decided at run time",
    )


def _publish(target: str, token: Secret[str]) -> str:
    """The trusted call: the only place the value is unwrapped."""
    return (
        f"published to {target} "
        f"with a {len(token.get_secret_value())}-character credential"
    )


@job(extra_description="Publish to a target, using the credential its group holds")
def publish(config: PublishConfig, vault: Vault, log: Log) -> str:
    """Read the target's credential, or report that nobody provisioned one."""
    try:
        token: Secret[str] = vault.read(config.target, "api_token")
    except VaultEntryMissingError:
        log(f"no credential provisioned for {config.target}; nothing published")
        return f"skipped {config.target}"
    summary = _publish(config.target, token)
    log(summary)
    return summary


@job(extra_description="Report the group's own flags, resolved without a read")
def group_status(options: CloudflareD1Options, log: Log) -> str:
    """The same entry `publish` reads by address, reached the config way."""
    provisioned = bool(options.api_token.get_secret_value())
    summary = f"cloudflare.d1 api_token is {'set' if provisioned else 'not set'}"
    log(summary)
    return summary
