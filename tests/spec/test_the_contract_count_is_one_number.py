"""Three documents claimed three different numbers of import contracts — AC-21.

Measured while executing `plugin-host-protocol`/T13, against
`grep -c '^\\[\\[tool.importlinter.contracts\\]\\]' pyproject.toml`, which
returns **7**:

- `pyproject.toml:236` said "the **six** contracts below" — in the same file
  as the contracts it was miscounting;
- `.spec/CONSTITUTION.md:11` said "**six**";
- `contributor/architecture/codemaps/dependencies.md:25` said "**five**", and
  its numbered list named five of the seven.

T13's gate was a grep run by hand. A number that three documents got wrong
independently will drift again the moment an eighth contract lands, so the
grep is a test: the count comes from `pyproject.toml`, and each document has
to state it.

This is deliberately a *count* check and not a prose check. It cannot tell you
the descriptions are right — `dependencies.md`'s list is checked by eye — but
the failure it prevents is the one that actually happened, three times.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

#: Each document, and the pattern that must carry the count as group 1.
CLAIMS = {
    "pyproject.toml": re.compile(r"the (\w+) contracts below"),
    ".spec/CONSTITUTION.md": re.compile(r"(\w+) `\[tool\.importlinter\]` contracts"),
    "contributor/architecture/codemaps/dependencies.md": re.compile(
        r"`uv run lint-imports`\), (\w+) contracts"
    ),
}

WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


def _declared_contracts() -> int:
    """The number of contracts `import-linter` will actually enforce."""
    with (ROOT / "pyproject.toml").open("rb") as fh:
        config = tomllib.load(fh)
    return len(config["tool"]["importlinter"]["contracts"])


def test_import_linter_has_contracts_at_all() -> None:
    """A zero here would make every assertion below vacuously true."""
    assert _declared_contracts() >= 5


@pytest.mark.parametrize("document", sorted(CLAIMS))
def test_each_document_states_the_real_count(document: str) -> None:
    text = (ROOT / document).read_text(encoding="utf-8")
    match = CLAIMS[document].search(text)
    assert match, (
        f"{document} no longer states a contract count in the expected shape "
        f"({CLAIMS[document].pattern!r}). Either the sentence was reworded — "
        "update this pattern — or the claim was dropped."
    )
    word = match.group(1).lower()
    claimed = WORDS.get(word)
    assert claimed is not None, f"{document} says {word!r}, which is not a number"
    assert claimed == _declared_contracts(), (
        f"{document} claims {word} ({claimed}) import contracts; "
        f"pyproject.toml declares {_declared_contracts()}"
    )


def test_the_codemap_names_every_contract() -> None:
    """The prose count and the list length are two claims, and both drifted.

    `dependencies.md` said "five" *and* listed five, while seven were
    enforced — so a reader checking the list against the number would have
    found them agreeing and both wrong.
    """
    text = (ROOT / "contributor/architecture/codemaps/dependencies.md").read_text()
    section = text.split("`[tool.importlinter]`:", 1)[1]

    # Only the contiguous run that opens the section. The document carries two
    # more numbered lists further down, and matching the whole tail counted 16.
    listed = []
    for line in section.lstrip("\n").splitlines():
        if re.match(r"^\d+\. ", line):
            listed.append(line)
        elif listed:
            break

    assert len(listed) == _declared_contracts(), (
        f"the codemap lists {len(listed)} contracts, "
        f"pyproject.toml declares {_declared_contracts()}:\n" + "\n".join(listed)
    )
