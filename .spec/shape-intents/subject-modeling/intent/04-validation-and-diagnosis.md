# 04 — Validation & Diagnosis

> **Status: contract current, mechanism superseded.** The two-step pipeline and
> the diagnosis record contract are intact and realized in
> [`../05-diagnosis-validation.md`](../05-diagnosis-validation.md). What changed is
> how: pydantic models with `extra="forbid"`, schemas *derived* via
> `rise schema export` — **there is no schema file anywhere in v3** — and the
> two runtime prerequisites are pydantic + stdlib, not a YAML parser and a
> schema validator. Ledger rows 5, 7.

The framework's enforcement mechanism is a **two-step validation pipeline**
plus a **diagnosis record contract**. Together they implement the promise
"errors are caught before execution."

## The two-step pipeline

```
module file ──(parse)──▶ structure ──(check 1: structure)──▶ ✓/✗
                                   └─(check 2: run diagnose, check output)─▶ ✓/✗
```

### Step 1 — Structure check

Parse the module file and validate the **whole document** against the contract
for its declared kind. The checker must verify:

1. The declaration block exists and is well-formed.
2. The declared kind is a known value (a file claiming an unknown kind is
   rejected — there is no schema for it).
3. Every required capability of that kind is present.
4. Every required configuration entry of that kind is declared.
5. Every required tag of that kind is present (e.g. a `program` without an
   isolation tag is invalid).
6. For each claimed interface: every interface-required capability and
   configuration entry is present (expressed as conditional rules keyed on the
   interface list).
7. Claimed interfaces are legal for the declared kind (scope check).

The structure check is **static**: it validates the file, not the machine.

### Step 2 — Diagnosis output check

Run the module's `diagnose` operation, capture the emitted record, and
validate **the record** against the diagnosis contract for that kind. The
checker must verify:

1. The record carries kind, interfaces, tags, and the fixed status value.
2. The kind matches what the schema for this kind expects.
3. Interfaces in the record are legal for the kind.
4. Kind-specific requirements on tags (isolation for programs; language and
   package-manager for libraries).
5. Kind-specific diagnosis blocks exist where required (programs and libraries
   must include a runtime block; static kinds must not).
6. No unknown top-level fields (closed record: a field the schema doesn't
   declare is an error, which catches typos and invented fields).

Step 2 is **dynamic**: it validates what the module reports about reality.

### Design intent of the split

- Step 1 catches **authoring** errors: missing capabilities, wrong kind, bad
  interface claims. Runs fast, no side effects.
- Step 2 catches **reality** errors: the module claims to be a `program` but
  its diagnose output is missing its runtime block; or the record contains a
  field that doesn't exist in the contract.
- Both steps use **the same standard schema language** as the rest of the
  ecosystem (a standard, draft-stable validation schema dialect). No bespoke
  validator: any conformant implementation of the standard produces identical
  results, which is the compatibility guarantee.
- **One schema file pair per kind** — a structure schema and a diagnosis
  schema — instead of one monolithic schema with kind-switching conditionals.
  Each pair is fully self-contained. Adding a kind = adding one pair; changing
  a kind never risks breaking another.

## Schema organization

Three distinct artifacts, three distinct jobs:

| Artifact | Job | Nature |
|---|---|---|
| **Metadata registry** | Enumerate the vocabulary: all kind names, all interface names, and the contract definitions (required capabilities/configuration/tags, allowed interfaces, diagnosis shape) | Data, machine-readable |
| **Structure schemas** (per kind) | Validate module files | Standard validation schema |
| **Diagnosis schemas** (per kind) | Validate diagnose records | Standard validation schema |

**Invariant:** the metadata registry must stay *metadata-only* — no validation
logic lives in it. Validation lives in the per-kind schemas; the registry is
the vocabulary dictionary that tools (schema management, listing commands,
documentation generators) read. The contract definitions in the registry are
the single source of truth that the schemas are generated from — the two must
never disagree.

## The diagnosis record contract

### Universal fields (all kinds)

```
DiagnosisRecord := {
  kind:       string   # from the declaration
  interfaces: list     # from the declaration
  tags:       map      # from the declaration, unwrapped
  result:     "N/A"    # literally this fixed string
}
```

The fixed `"N/A"` status is deliberate: it means "this record is
structurally valid; the meaningful status lives in the runtime block." Static
kinds (base, meta, host, registry, workflow) emit **only** these fields —
their correctness is proven by successful emission.

### Program runtime block

```
ProgramDiagnosis := {
  program:    name
  isolation:  host | project | process
  platform:   { os, arch }                      # detected at run time
  installed:  {
    status:    "installed" | "not_installed"
    version:   string                           # empty when not installed
    path:      absolute path                    # empty when not installed
    origin:    which variant produced it        # empty when not installed
    detected_by: how origin was determined      # e.g. "path lookup"
  }
  capabilities: {
    can_install:   bool   # the installer for this variant is available
    can_update:    bool
    can_uninstall: bool   # the removal path exists
    can_run:       bool   # binary found on path
    runs_correctly: bool  # verified by actually executing a benign probe
    verified_by:   string # which probe was used, e.g. "version check"
  }
}
```

Contract subtleties:

- `runs_correctly` must be **verified, not assumed** — it requires actually
  running the binary (a `--version`-style probe) at diagnose time.
- `detected_by` documents the *method* used to conclude the origin, so
  consumers can decide how much to trust it.
- The whole record is the **single source of truth**: install/uninstall/invoke
  logic consults diagnose output instead of re-implementing detection.

### Library runtime block

Same philosophy, different detection physics: existence is proven by
**importing the package in its language**, not by path lookup.

```
LibraryDiagnosis := {
  library:   name
  language:  "python" | "javascript" | "rust" | …
  platform:  { os, arch }
  installed: {
    status:        "installed" | "not_installed"
    version:       string
    import_path:   where the package physically lives
    origin:        which package manager
    detected_by:   "import check"
  }
  capabilities: {
    can_install:    bool
    can_update:     bool
    can_uninstall:  bool
    import_verified: bool   # the import actually succeeded
  }
}
```

### Service runtime block

```
ServiceDiagnosis := {
  service:  name
  status:   "running" | "stopped" | "unknown"    # detected, not declared
  platform: { os, arch }
}
```

### Why JSON-lines

One module → one line. A tree of modules → many lines, dependencies before
dependents. Properties that matter:

- Each line is independently parseable (streaming, resumable audits).
- Grep is the query language for "all host-level operations", "all failures".
- An agent can feed the whole tree to a schema checker without any glue code.

## Delegation of detection: the callout pattern

The generic diagnosis logic needs per-tool *probes* (where's the binary, what
version, can we install it). The contract:

- The framework owns the **shape** of the record and the **detection
  algorithm** (run the probes, assemble the record).
- Each module supplies **only the probes** — small shell/expression snippets
  that answer one question each ("is X on the path?", "what version?", "can
  the package manager see it?"), expressed in a way the framework can run.
- Unsupplied probes fall back to safe generic defaults (path lookup by the
  declared name, version probe by convention).

This split is what makes the diagnosis pipeline **generic across every tool
while staying accurate per tool**.

## The extraction invariant

One subtle correctness requirement, easy to miss in a re-implementation:

When a module includes another module, their declaration blocks must never
silently collide. Specifically, the validation of a module must read **that
module's own declaration as it exists on disk**, immune to any
variable-resolution quirk of the underlying task runner (some runners
substitute the *included* module's variables over the *including* module's —
which would silently swap identities). The checker must therefore extract the
declaration from the file directly rather than from the runner's resolved
variable space.

**Pseudocode:**

```
function extract_declaration(module_path):
    raw = parse_file(module_path)
    decl = raw.declaration
    if decl is missing: fail("module has no declaration")
    # never consult the runner's merged variable view for this
    return decl

function diagnose_module(module_path, kind):
    decl = extract_declaration(module_path)      # from disk
    probes = module_probes(kind, decl)           # supplied or defaults
    runtime = run_probes(probes)                 # if kind requires runtime block
    record = build_record(decl, runtime, "N/A")
    emit(record as one line)
```

## Validation pseudocode

```
function validate_module(module_path):
    file_data = parse(module_path)               # step 1 input
    kind = extract_kind(file_data)
    if kind not in known_kinds: fail("unknown kind")
    structure_schema = structure_schemas[kind]   # error if absent
    check(file_data, structure_schema)           # step 1

    record = run_diagnose(module_path)           # step 2 input
    diagnosis_schema = diagnosis_schemas[kind]
    check(record, diagnosis_schema)              # step 2

function validate_tree(root_module):
    for dependency in walk(root_module, order=dependencies-first):
        validate_module(dependency)              # one record each; stream
    validate_module(root_module)
```

## Prerequisites discipline

The two checks are allowed exactly **two** runtime prerequisites: a YAML
parser and a standard-schema validator for the implementation language. No
JSON-query CLI, no other tooling in the pipeline. Keeping the validator's
footprint minimal is what makes the pipeline portable and the framework's
"bootstrap the validator" story trivial.
