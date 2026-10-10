# Spec: self update verifies the SHA256SUMS this repository publishes

Shape state: not-required — a defect fix with no new user-visible surface; the
command, its output and its exit codes are unchanged except that an update that
was always refused now succeeds.

## Problem

`func builtin self update` on a standalone binary downloads the release archive
and `SHA256SUMS`, then checks the archive against the line that names it
(`src/functualize/_cli/self_update.py:153` `verify`). The release workflow
writes that file with

```
sha256sum ./* > SHA256SUMS            # .github/workflows/release.yml:508
```

GNU `sha256sum` echoes the path it was given, so every published line reads
`<digest>  ./functualize-<target>.<ext>`. `verify` strips a leading `*`
(binary-mode marker) and then compares against the bare asset name it took from
the release's asset list (`perform`, `self_update.py:344`). No line ever
matches, and every update since the standalone binary first shipped (0.2.2)
fails with `<asset> is not listed in SHA256SUMS`.

The fail-closed half did its job: nothing was ever installed unverified. The
defect is that the verifying half can never succeed.

## Which side is normalised — both, for different reasons

**The reader tolerates the prefix.** A `SHA256SUMS` line names a file the way
the tool that produced it was given it. `./name` and `*name` (binary mode, and
`*./name` when both apply) are ordinary `sha256sum` output and name the same
asset as `name`. `sha256sum -c`, which the installation docs tell users to run,
accepts all three; both installers already do (`install.sh` `verify` matches
`[ *]\.?/?<name>$`; `install.ps1` matches the name at the end of the line). The
Python reader is the only consumer that does not, so it is brought in line with
the other three rather than made the one exception the writer must cater to.

**The writer emits bare names.** The reader fix only helps binaries built
*after* it. Every standalone binary already installed — 0.2.2 through 0.4.0 —
carries the old reader, and those binaries update by verifying the *next*
release's `SHA256SUMS`. If that file still says `./name`, none of them can ever
update, and their users are told the release is unverifiable. Writing bare
names (`sha256sum * > SHA256SUMS`) makes the next release verifiable by every
binary in the field, old reader or new. The file's contents — which assets it
covers — are unchanged; only how each line spells the name.

The two halves agree: the writer emits the form every reader accepts, and the
reader accepts every form the writer has ever emitted.

## Acceptance criteria

- **AC1** — A line `<digest>  ./functualize-x86_64-unknown-linux-gnu.tar.gz`
  verifies a download whose asset name is
  `functualize-x86_64-unknown-linux-gnu.tar.gz`. The `./` prefix, the `*`
  binary-mode marker, both together (`*./name`), and the bare name each verify,
  and each is covered by a test.
- **AC2** — Tolerance never widens what passes. A line whose name matches but
  whose digest differs raises `ChecksumMismatchError` naming both digests; an
  asset with no line at all raises `ChecksumMismatchError` as "not listed". A
  name that only *ends* with the asset name (`other-functualize-….tar.gz`,
  `dir/functualize-….tar.gz`) is not the asset and does not match.
- **AC3** — The release workflow's checksum step writes bare names, and a test
  reads the step's command out of `.github/workflows/release.yml` itself, runs
  it, and verifies the result through `verify` — so the writer and the reader
  are seen to agree, and a later edit to either that breaks the agreement fails
  the suite.
- **AC4** — End to end through the real path: a release-style directory
  checksummed with `sha256sum ./*` (every release published to date) is
  verified through `perform`, the function `func builtin self update` calls, and
  the binary is replaced.

## Out of scope

- Whether `SHA256SUMS` should also cover signature or provenance assets.
- The update channel, and any rollback path.
- `install.ps1`'s end-of-line match, which accepts any line *ending* in the
  asset name. It is a separate looseness in a separate reader; noted, not fixed.
