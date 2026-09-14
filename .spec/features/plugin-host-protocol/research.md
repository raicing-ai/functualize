# Research: plugin-host-protocol

## Research question

What is the smallest typed extension contract that lets plugin and provider authors
write against the current Functualize application surface without creating a
speculative “god protocol”?

## Starting point

This branch starts at `origin/master` `aed582e`. The current code has:

- `RemoteProvider` in `src/functualize/_config/protocols.py`;
- provider registration in `src/functualize/_config/registry.py`;
- plugin loading and invocation in `src/functualize/_plugins/loader.py`;
- `AdapterPlugin.__call__(app: Any)` in `src/functualize/_types/protocols.py`;
- several first-party plugins still annotating `app: Any`.

The existing draft proposed moving `RemoteProvider`, adding role protocols,
and typing many plugin call sites. That draft is useful evidence, but it was
written against an older branch and must not be adopted verbatim.

## Findings

1. Provider registration and general plugin registration are different contracts.
   A remote provider needs only the provider registry; an adapter plugin may need
   lifecycle, events, commands, or execution surfaces.
2. The framework currently relies on duck-typed plugin loading. Adding a static
   protocol does not automatically create runtime validation.
3. The current provider path is entry-point based and already has a concrete
   public-user workflow in the AWS and Bitwarden plugins.
4. A single protocol containing every application member would make provider
   plugins depend on unrelated capabilities and would make future surface
   changes unnecessarily breaking.
5. The vault work should not depend on speculative plugin-host features beyond
   the provider contract needed by sync.

## Recommended scope

Start with a narrow, evidence-backed contract:

- make `RemoteProvider` publicly importable from the intended public namespace,
  while preserving internal imports during the pre-1.0 transition;
- define the smallest registration capability required by remote-provider
  plugins;
- type-check one real provider plugin and one representative adapter plugin;
- add a static negative test proving a misspelled registration member fails mypy;
- do not create a nine-member `PluginHost` until multiple real clients require
  the same combined surface;
- do not change loader behavior in this feature unless a concrete runtime error
  is demonstrated.

## User-experience questions

- Can a provider author discover the correct import and registration path from
  `func builtin info` or documentation?
- Does a bad provider fail at development/type-check time rather than during
  application boot?
- Does the error explain which plugin contract is missing and how to fix it?
- Can a provider plugin be tested without booting an unrelated CLI/TUI surface?

## Dependencies and sequencing

This feature should precede `vault-sync-providers`, because provider authors
need a stable public contract. It does not block `local-vault-access`, which
can use the local store without any remote provider.

## Open decisions

- Whether `RemoteProvider` belongs in `functualize.plugin` or another public
  namespace that better represents configuration providers.
- Whether compatibility re-exports are acceptable for the pre-1.0 codebase.
- Whether provider registration should remain entry-point-only or gain a public
  application registration helper.
- Which plugin categories actually need a shared host protocol after measuring
  current call sites.

## Recommendation

Specify and implement the narrow provider-facing contract first. Defer the broad
`PluginHost` design until the measured client matrix proves it is needed.

