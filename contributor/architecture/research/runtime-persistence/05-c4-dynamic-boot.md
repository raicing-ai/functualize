# C4 dynamic — provider boot and binding

```mermaid
C4Dynamic
  title Boot - Select, Migrate, Validate, and Bind One Runtime Provider

  Component(plugin, "Persistence Plugin", "Public plugin API", "Registers a lazy provider factory")
  Component(composition, "Composition Root", "_app", "Owns ordered boot")
  Component(config, "Config Resolution", "_config", "Produces PersistenceSelection")
  Component(registry, "Provider Registry", "_persistence", "Maps scheme/name to factory")
  Component(factory, "Selected Provider Factory", "Plugin", "Constructs provider from resolved settings")
  Component(provider, "Runtime Persistence Provider", "Plugin implementation", "Migrations, health, UoW, queries, admin")
  Component(handle, "Bind-once Persistence Handle", "_persistence", "Stable engine dependency")
  Component(engine, "Execution Engine", "_engine", "Cannot execute before binding")
  ContainerDb(db, "Runtime Database", "Selected backend", "Schema and runtime data")

  Rel(composition, plugin, "1. Load plugin and request registration")
  Rel(plugin, registry, "2. Register factory and supported scheme")
  Rel(composition, config, "3. Resolve program-level persistence selection")
  Rel(config, composition, "4. Return one explicit/default selection")
  Rel(composition, registry, "5. Resolve factory; reject zero/multiple explicit matches")
  Rel(registry, factory, "6. Return factory")
  Rel(composition, factory, "7. Construct provider without side-effect fallback")
  Rel(factory, provider, "8. Return typed provider and capabilities")
  Rel(composition, provider, "9. Validate capabilities, migrate, and health-check")
  Rel(provider, db, "10. Apply checksummed migrations and probe")
  Rel(composition, handle, "11. Bind provider exactly once")
  Rel(handle, engine, "12. Make persistence ready before APP_READY/execution")

  UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="1")
```

## Failure semantics

- No explicit selection: bind the document compatibility provider.
- Explicit selection whose plugin/driver is absent: fail boot and name the
  install/config remedy.
- Migration/health failure: fail boot; never fall back to a local backend.
- Second bind: programming/configuration error.
- Static boot: uses an explicitly provided provider/factory or the zero-I/O
  document compatibility provider; it performs no entry-point scan.
