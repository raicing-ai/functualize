"""Refuse a pull request whose text carries internal bookkeeping or a machine.

A squash merge publishes the pull request title as the commit subject and the
pull request body as the commit body, so three texts become a permanent, public
record of this repository: the title, the body, and every commit message in the
PR's range. Three classes of string belong to neither.

1. **A tracker key or tracker URL.** The tool that dispatches work keeps keys of
   the shape ``<PREFIX>-<NUMBER>`` and its own hostnames. Nothing in this
   repository can resolve either, and writing one down says nothing a reader of
   the change needs. It also publishes an internal workflow into a public
   record. A plain GitHub issue reference (``Fixes #123``) is not this class:
   it is public and it is this repository's own tracker.

2. **An internal identifier** — a task, run or workspace id. It is opaque here,
   it expires with the platform that minted it, and it is not a citation.

3. **A machine identity** — an agent, model, harness or automation account named
   as an author. Attribution records who is accountable for the change, and a
   tool is not. The shape this arrives in is a ``Co-authored-by:`` trailer, and
   once squash-merged it is permanent.

Nothing in this file names the tracker, one of its keys, or any agent. The
``-<NUMBER>`` suffixes this repository may legitimately use are listed as
*permitted*, so an unknown prefix is refused without any tracker prefix being
written into the repository; and identity strings that must never be committed
are read from the ``MESSAGE_HYGIENE_IDENTITY_DENYLIST`` repository variable,
which is a repository *setting* rather than a file.

Inputs, all from the environment so the workflow owns the git invocation:

``MESSAGE_HYGIENE_TITLE``  the PR title
``MESSAGE_HYGIENE_BODY``   the PR body (optional)
``MESSAGE_HYGIENE_LOG``    a file with the range's commit messages (optional)
``MESSAGE_HYGIENE_IDENTITY_DENYLIST``  comma-separated, case-insensitive
``MESSAGE_HYGIENE_REVIEWER_ALLOWLIST`` comma-separated addresses
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# Prefixes that legitimately carry a `-<number>` suffix in this repository's own
# prose: ADRs, acceptance criteria, task and phase labels, and standard
# identifiers (`UTF-8`, `ISO-8601`, `SHA-256`, `PEP-723`, licence names).
# Measured, not designed, over tracked files and every commit message with
#   git ls-files -z | xargs -0 grep -ohE '\b[A-Z]{2,10}-[0-9]{1,6}\b' \
#     | sed 's/-[0-9]*$//' | sort -u
# `RFC` is the one entry that is a class rather than a measurement: an IETF
# document reference (`RFC-2119`) is a citation, not a ticket, and none appears
# in this repository yet.
#
# Everything else is refused, which is what keeps a tracker key out of the
# repository without the tracker being named here. Growth: a benign token that an
# unlisted prefix refuses is added to this set in a PR.
PERMITTED_PREFIXES = frozenset(
    {
        "AC",
        "ADR",
        "AES",
        "AFL",
        "BF",
        "BSD",
        "CF",
        "CI",
        "CURRENT",
        "EAST",
        "FACT",
        "GAP",
        "GH",
        "GO",
        "GPL",
        "IF",
        "INV",
        "ISO",
        "LGPL",
        "LICENSE",
        "NFR",
        "ORD",
        "PEP",
        "PM",
        "PR",
        "REFUSED",
        "RFC",
        "SEP",
        "SHA",
        "TD",
        "TS",
        "US",
        "UTF",
        "WIDGET",
    }
)

# Trailer keys that attribute the change to somebody, and so must name a person
# rather than a machine.
ATTRIBUTION_SUFFIX = "-by"

_KEY = re.compile(r"\b([A-Z]{2,10})-([0-9]{1,6})\b")
_URL = re.compile(r"https?://[^\s<>()\[\]\"'`]+")
_URL_SEGMENT = re.compile(r"/([A-Z]{2,10})(?=[/?#]|$)")
# A git ref in a URL path is not a tracker key (`/blob/HEAD/...`).
PERMITTED_URL_SEGMENTS = PERMITTED_PREFIXES | {"HEAD"}
# A truncated run id (`deadbeef-0bad`) and the full UUID form are one shape.
_RUN_ID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}(?:-[0-9a-f]{4}){0,2}(?:-[0-9a-f]{12})?\b"
)
_TRAILER = re.compile(r"^([A-Za-z][A-Za-z0-9-]*):[ \t]*(\S.*)$")
_ADDRESS = re.compile(r"<([^<>\s]+@[^<>\s]+)>|([^\s<>,]+@[^\s<>,]+\.[A-Za-z]{2,})")

CLASSES = {
    "tracker": "a tracker key or tracker URL",
    "identifier": "an internal identifier",
    "identity": "a machine identity",
}


def _split_values(raw: str) -> list[str]:
    """A comma- or newline-separated repository variable, trimmed."""
    return [item.strip() for item in re.split(r"[,\n]", raw) if item.strip()]


def _paragraph_trailers(text: str) -> list[tuple[str, str]]:
    """The `Key: value` lines of each paragraph's trailing block.

    Only a paragraph's last contiguous run of trailer-shaped lines counts, which
    is git's own shape: it is what keeps a body sentence that happens to open
    with `Note:` out of the trailer block.
    """
    trailers: list[tuple[str, str]] = []
    for paragraph in re.split(r"\n[ \t]*\n", text):
        block: list[tuple[str, str]] = []
        for line in paragraph.splitlines():
            match = _TRAILER.match(line.strip())
            if match is None:
                block = []
                continue
            block.append((match.group(1), match.group(2)))
        trailers.extend(block)
    return trailers


def find_violations(
    title: str,
    body: str,
    log: str,
    *,
    denylist: list[str],
    reviewer_allowlist: list[str],
) -> list[str]:
    """Every refused string in the three texts, as `<source>: <reason>` lines."""
    texts = (("PR title", title), ("PR body", body), ("commit messages", log))
    violations: list[str] = []

    for source, text in texts:
        if not text:
            continue
        for line in text.splitlines() or [text]:
            for prefix, number in _KEY.findall(line):
                if prefix not in PERMITTED_PREFIXES:
                    violations.append(
                        f"{source}: tracker key `{prefix}-{number}` "
                        f"({CLASSES['tracker']}) — {line.strip()}"
                    )
            for url in _URL.findall(line):
                for segment in _URL_SEGMENT.findall(url):
                    if segment not in PERMITTED_URL_SEGMENTS:
                        violations.append(
                            f"{source}: tracker URL `{url}` carries the key "
                            f"prefix `{segment}` ({CLASSES['tracker']})"
                        )
            for internal_id in _RUN_ID.findall(line):
                violations.append(
                    f"{source}: internal identifier `{internal_id}` "
                    f"({CLASSES['identifier']}) — {line.strip()}"
                )
            for needle in denylist:
                if needle.lower() in line.lower():
                    violations.append(
                        f"{source}: identity string `{needle}` "
                        f"({CLASSES['identity']}) — {line.strip()}"
                    )

    for source, text in (("PR body", body), ("commit messages", log)):
        for key, value in _paragraph_trailers(text):
            attributes = key.lower().endswith(ATTRIBUTION_SUFFIX) or key.lower() in {
                "author",
                "committer",
                "generated",
                "assisted",
            }
            if not attributes and "@" not in value:
                continue
            match = _ADDRESS.search(value)
            address = (match.group(1) or match.group(2)) if match else None
            if address is None:
                violations.append(
                    f"{source}: trailer `{key}:` names no address "
                    f"({CLASSES['identity']}) — a trailer that attributes a "
                    "change must name a person with an address"
                )
            elif not reviewer_allowlist:
                violations.append(
                    f"{source}: trailer `{key}:` cannot be validated — "
                    "`MESSAGE_HYGIENE_REVIEWER_ALLOWLIST` is not set, so no "
                    f"attributed address is accepted ({CLASSES['identity']})"
                )
            elif address.lower() not in reviewer_allowlist:
                violations.append(
                    f"{source}: trailer `{key}:` names `{address}`, which is "
                    f"not on the reviewer allow-list ({CLASSES['identity']}) — a "
                    "trailer records a person accountable for the change; a tool "
                    "is not one"
                )

    return violations


def main() -> int:
    title = os.environ.get("MESSAGE_HYGIENE_TITLE", "")
    body = os.environ.get("MESSAGE_HYGIENE_BODY", "")
    log_path = os.environ.get("MESSAGE_HYGIENE_LOG", "")
    log = ""
    if log_path:
        try:
            log = Path(log_path).read_text(encoding="utf-8")
        except OSError as error:
            print(f"::error::cannot read the commit-message log: {error}")
            return 1
    denylist = _split_values(os.environ.get("MESSAGE_HYGIENE_IDENTITY_DENYLIST", ""))
    reviewer_allowlist = [
        address.lower()
        for address in _split_values(
            os.environ.get("MESSAGE_HYGIENE_REVIEWER_ALLOWLIST", "")
        )
    ]

    if not title.strip():
        print("::error::MESSAGE_HYGIENE_TITLE is empty; nothing was checked.")
        return 1

    violations = find_violations(
        title,
        body,
        log,
        denylist=denylist,
        reviewer_allowlist=reviewer_allowlist,
    )
    if violations:
        # The message is the rule's own wording, because it lands in a PR's
        # checks tab more often than this file is read.
        print(
            f"::error::This PR's text carries {len(violations)} forbidden "
            "string(s): a tracker key or tracker URL, an internal identifier, or "
            "a machine identity."
        )
        for violation in violations:
            print(f"::error::{violation}")
        print(
            "::error::Say what the change does, in the project's own terms. The "
            "tracking context and the tooling that produced the change live in "
            "the tracker, not in the record. See CONTRIBUTING.md § Commit "
            "Message Convention."
        )
        return 1

    print(
        "OK: the PR title, PR body and commit messages carry no tracker key or "
        "URL, no internal identifier, and no machine identity."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
