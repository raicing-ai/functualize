# Contracts: self-update-checksum-prefix

## `functualize._cli.self_update.verify` — signature unchanged

```python
def verify(archive: bytes, checksums: str, asset_name: str) -> None: ...
```

Internal (`_cli/`), one production caller: `perform` (`self_update.py:344`).

### Accepted `SHA256SUMS` line

`<hex digest><whitespace><name>`, exactly two whitespace-separated fields.
`<name>` identifies `asset_name` when, after removing **one** leading `*`
(binary-mode marker) and then **one** leading `./`, it equals `asset_name`
exactly.

| Line name | Asset `a.tar.gz` |
|---|---|
| `a.tar.gz` | match |
| `./a.tar.gz` | match |
| `*a.tar.gz` | match |
| `*./a.tar.gz` | match |
| `x-a.tar.gz`, `dir/a.tar.gz`, `../a.tar.gz` | no match |

Before this change the marker was removed with `lstrip("*")` (any number of
stars); one is all `sha256sum` writes, so `**a.tar.gz` no longer matches.

### Outcomes (unchanged)

- matching line, equal digest (case-insensitive) → returns `None`
- matching line, different digest → `ChecksumMismatchError("<asset>: published <p>, downloaded <d>")`
- no matching line → `ChecksumMismatchError("<asset> is not listed in SHA256SUMS")`

## Release asset `SHA256SUMS` — line spelling changes

Written by the `checksums` job of `.github/workflows/release.yml`. Covers the
same assets as before; each line now names its asset bare (`<digest>  <asset>`)
instead of `<digest>  ./<asset>`. `sha256sum -c SHA256SUMS --ignore-missing`
behaves identically on both.
