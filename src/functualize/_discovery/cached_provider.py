"""Cache-backed job discovery provider — the single discovery cache system.

Contains CachedDirectoryScanProvider, a cache-first JobProvider with O(1)
name lookup. It owns the single persisted discovery cache file
(`cache.json`, resolved via ResourceLocator — see `cache_format.py` for the
format and location rules).

Satisfies the JobProvider Protocol via structural typing. Cache entries are
validated with tiered checks before use:
- Tier 1: mtime-based check (single stat() call)
- Tier 2: sha256 content hash comparison (mtime changed, content identical)
- Tier 3: dependency hash verification (first-level in-project imports)

Global invalidation triggers (checked on load; the whole cache is discarded
and the file deleted when any fires):
- cache format version change
- functualize version change
- Python version change
- pyproject.toml [project.dependencies] hash change

Negative pre-filter decisions are persisted in the same file to avoid
repeated AST parses across restarts.

Supports incremental updates on list_jobs() and single-module re-import on
get_job(name) when cache entries are stale.

Silent recovery on corrupted/missing cache — starts empty and rebuilds on demand.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import os
import pkgutil
import platform
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from functualize._primitives.cache_format import (
    CACHE_FILENAME,
    CACHE_VERSION,
    DisplayCacheEntry,
    PreFilterDecision,
    compute_deps_hash,
    get_functualize_version,
)
from functualize._types.descriptors import (
    CacheInfo,
    GroupOptionsSpec,
    JobDescriptor,
)
from functualize._types.errors import GroupOptionsConflictError

if TYPE_CHECKING:
    from functualize._primitives.job_filter import JobFilter
    from functualize._primitives.locator import ResourceLocator
    from functualize._primitives.pre_filter import ModulePreFilter

logger = logging.getLogger(__name__)


class CachedDirectoryScanProvider:
    """Cache-first JobProvider with O(1) name-based lookup.

    Uses the persisted discovery cache to avoid re-importing modules on every
    boot. Cache entries are validated via tiered checks before use. Invalid
    entries trigger re-import of the affected module only.

    Satisfies the JobProvider Protocol via structural typing:
    - list_jobs() -> Sequence[JobDescriptor]
    - get_job(name: str) -> JobDescriptor | None

    Args:
        directories: List of directory paths to scan for job modules.
        locator: ResourceLocator instance for cache storage path resolution.
        pre_filter: Optional ModulePreFilter to filter modules before import.
        job_filter: Optional JobFilter for the ``require_job_*`` settings.
            Applied on *read* rather than on write, so the cache stays a
            superset of what any one filter config admits and a changed
            job-level filter takes effect without a cache rebuild.
        project_root: Project root directory, used for the deps-hash global
            invalidation check and module import context. Defaults to the
            parent of the first configured directory.
    """

    def __init__(
        self,
        directories: list[str],
        locator: ResourceLocator,
        pre_filter: ModulePreFilter | None = None,
        job_filter: JobFilter | None = None,
        project_root: Path | None = None,
        discovery_hash: str | None = None,
    ) -> None:
        self._directories = directories
        self._locator = locator
        self._pre_filter = pre_filter
        self._job_filter = job_filter
        # Fingerprint of the discovery config the above filters were built from.
        # A cache written under one filter set and replayed under another is
        # wrong in both directions, so a mismatch discards the whole file.
        #
        # None means "this provider does not know the discovery config" — not
        # "there is no config" — so such a provider skips the check rather than
        # asserting the empty config. Without the skip, a bare provider built
        # over a directory with no config in hand would fail the comparison
        # against any cache written under an active filter and delete it.
        #
        # In practice the skip only ever decides the *matching-cache* case:
        # every `func builtin` command boots a full app first (`_cli/main.py`
        # builds a FunctualizeApp in the `cli_app` callback), so a genuinely
        # stale cache has already been invalidated and rebuilt by a
        # config-aware provider before a bare one gets to read it.
        self._discovery_hash = discovery_hash
        if project_root is not None:
            self._project_root = Path(project_root)
        elif directories:
            self._project_root = Path(directories[0]).parent
        else:
            self._project_root = Path.cwd()

        # In-memory cache: keyed by composite "source_file::job_name"
        self._entries: dict[str, JobDescriptor] = {}
        # O(1) name-based index: job_name -> JobDescriptor
        self._by_name: dict[str, JobDescriptor] = {}

        # Pre-filter decision cache: source_file -> PreFilterDecision
        # Only negative decisions (eligible=False) are stored
        self._pre_filter_decisions: dict[str, PreFilterDecision] = {}

        # Display-provider records: source_file -> DisplayCacheEntry.
        # Written by the scan's display-detection pass; read (via the raw
        # JSON, not this provider) by the TUI so it imports only flagged
        # modules at startup.
        self._display_entries: dict[str, DisplayCacheEntry] = {}

        # Group-options records: group_path -> GroupOptionsSpec. Keyed by the
        # declared path (not the source file) because every consumer asks
        # "what flags does this group accept?"; one declaration per path is
        # enforced at record time.
        self._group_options_entries: dict[str, GroupOptionsSpec] = {}

        # Set when in-memory state diverges from disk (e.g. Tier 2 mtime refresh)
        self._dirty = False

        # Load persisted cache (silent recovery on failure)
        self._load_cache()

    # =========================================================================
    # JobProvider Protocol
    # =========================================================================

    def list_jobs(self) -> Sequence[JobDescriptor]:
        """Return all valid job descriptors via incremental cache validation.

        Performs:
        1. Discover module files on disk across configured directories.
        2. Import new files not yet in cache.
        3. Re-import modified files (tiered validation failed).
        4. Remove entries for deleted files.
        5. Persist updated cache to disk.
        """
        on_disk = self._discover_module_files()

        cached_files = self._known_source_files()
        changed = False

        # New files: import and add to cache
        for source_file in on_disk - cached_files:
            if self._should_import_with_cache(source_file):
                descriptors = self._safe_import(source_file)
                for desc in descriptors:
                    self._add_entry(desc)
                if descriptors:
                    changed = True

        # Deleted files: remove from cache
        for source_file in cached_files - on_disk:
            self._remove_entries_for_file(source_file)
            changed = True

        # Clean up pre-filter decisions for deleted files
        for source_file in set(self._pre_filter_decisions.keys()) - on_disk:
            del self._pre_filter_decisions[source_file]
            self._dirty = True

        # Existing files: tiered validation, re-import if stale
        for source_file in on_disk & cached_files:
            if not self._validate_entries_for_file(source_file):
                self._remove_entries_for_file(source_file)
                descriptors = self._safe_import(source_file)
                for desc in descriptors:
                    self._add_entry(desc)
                changed = True

        if changed or self._dirty:
            self._persist_cache()

        return [d for d in self._by_name.values() if self._admits(d)]

    def get_job(self, name: str) -> JobDescriptor | None:
        """Retrieve a specific job by name with O(1) dict lookup.

        Flow:
        1. Dict lookup in _by_name.
        2. If found, validate via Tier 1 (mtime) + Tier 2 (sha256).
        3. If valid, return cached descriptor.
        4. If invalid, re-import single module and update.
        5. If not in cache, attempt targeted discovery.
        """
        # O(1) lookup. Descriptors are keyed by the canonical name, so a
        # caller holding the Python spelling (`test_suite` for the registered
        # `test-suite`) is answered by the same policy every other lookup in
        # the system uses, rather than getting a bare None.
        descriptor = self._resolve_entry(name)
        if descriptor is not None:
            name = descriptor.name

        if descriptor is not None:
            if self._is_entry_valid(descriptor):
                # Tier 2 may have refreshed the entry in place
                return self._admitted(self._by_name.get(name))
            # Stale — re-import the module
            source_file = descriptor.source_file
            self._remove_entries_for_file(source_file)
            new_descriptors = self._safe_import(source_file)
            for desc in new_descriptors:
                self._add_entry(desc)
            self._persist_cache()
            return self._admitted(self._by_name.get(name))

        # Not in cache — targeted discovery
        return self._admitted(self._targeted_discovery(name))

    def _admits(self, descriptor: JobDescriptor) -> bool:
        """Return True if the job-level filter admits this descriptor."""
        return self._job_filter is None or self._job_filter.should_register(descriptor)

    def _admitted(self, descriptor: JobDescriptor | None) -> JobDescriptor | None:
        """Pass the descriptor through the job-level filter (None if rejected).

        A filtered-out job must be unreachable by name too, not merely hidden
        from listings — otherwise ``func <name>`` would run a job that
        ``func`` does not list.
        """
        if descriptor is None:
            return None
        return descriptor if self._admits(descriptor) else None

    # =========================================================================
    # Cache persistence
    # =========================================================================

    def _load_cache(self) -> None:
        """Load cache from disk. Silent recovery on any failure.

        Applies the format-version check and global invalidation checks;
        when any fires, the cache starts empty and the stale file is deleted.
        """
        try:
            cache_path = self._locator.resolve_one(CACHE_FILENAME)
            if cache_path is None:
                return

            raw = Path(cache_path).read_text(encoding="utf-8")
            data = json.loads(raw)

            if not isinstance(data, dict) or not isinstance(data.get("entries"), dict):
                logger.warning("Discovery cache has invalid structure, starting empty")
                self._delete_cache_file(cache_path)
                return

            if data.get("version") != CACHE_VERSION:
                logger.warning(
                    "Cache version mismatch (expected %d, got %r), discarding",
                    CACHE_VERSION,
                    data.get("version"),
                )
                self._delete_cache_file(cache_path)
                return

            if self._is_globally_invalidated(data):
                self._delete_cache_file(cache_path)
                return

            for key, entry_data in data["entries"].items():
                try:
                    descriptor = JobDescriptor.from_dict(entry_data)
                    self._entries[key] = descriptor
                    self._by_name[descriptor.name] = descriptor
                except (ValueError, TypeError, KeyError) as e:
                    logger.warning("Failed to deserialize cache entry '%s': %s", key, e)

            decisions_data = data.get("pre_filter_decisions", {})
            if isinstance(decisions_data, dict):
                for key, decision_data in decisions_data.items():
                    try:
                        decision = PreFilterDecision.from_dict(decision_data)
                        self._pre_filter_decisions[key] = decision
                    except (ValueError, TypeError, KeyError) as e:
                        logger.warning(
                            "Failed to deserialize pre-filter decision '%s': %s",
                            key,
                            e,
                        )

            displays_data = data.get("displays", {})
            if isinstance(displays_data, dict):
                for key, display_data in displays_data.items():
                    try:
                        self._display_entries[key] = DisplayCacheEntry.from_dict(
                            display_data
                        )
                    except (ValueError, TypeError, KeyError) as e:
                        logger.warning(
                            "Failed to deserialize display entry '%s': %s", key, e
                        )

            group_options_data = data.get("group_options", {})
            if isinstance(group_options_data, dict):
                for key, spec_data in group_options_data.items():
                    try:
                        self._group_options_entries[key] = GroupOptionsSpec.from_dict(
                            spec_data
                        )
                    except (ValueError, TypeError, KeyError) as e:
                        logger.warning(
                            "Failed to deserialize group options entry '%s': %s", key, e
                        )
        except (OSError, json.JSONDecodeError, Exception) as e:
            logger.warning("Failed to load discovery cache (starting empty): %s", e)
            self._entries = {}
            self._by_name = {}
            self._pre_filter_decisions = {}
            self._display_entries = {}
            self._group_options_entries = {}

    def _persist_cache(self) -> None:
        """Write the current cache state to disk. Silent on failure."""
        try:
            cache_path = self._locator.writable(CACHE_FILENAME)
            data: dict[str, Any] = {
                "version": CACHE_VERSION,
                "functualize_version": get_functualize_version(),
                "python_version": platform.python_version(),
                "deps_hash": compute_deps_hash(self._project_root),
                "discovery_hash": self._discovery_hash,
                "generated_at": datetime.now(UTC).isoformat(),
                "entries": {
                    key: descriptor.to_dict()
                    for key, descriptor in self._entries.items()
                },
                "pre_filter_decisions": {
                    key: decision.to_dict()
                    for key, decision in self._pre_filter_decisions.items()
                },
                "displays": {
                    key: entry.to_dict() for key, entry in self._display_entries.items()
                },
                # Keyed by group path, not source file: the consumers ask
                # "what flags does `deploy` accept?", and one declaration per
                # path is enforced at record time.
                "group_options": {
                    key: spec.to_dict()
                    for key, spec in self._group_options_entries.items()
                },
            }
            cache_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            self._dirty = False
        except Exception as e:
            logger.warning("Failed to persist discovery cache: %s", e)

    def _is_globally_invalidated(self, data: dict[str, Any]) -> bool:
        """Check if global invalidation triggers require cache discard."""
        cached_version = data.get("functualize_version")
        current_version = get_functualize_version()
        if cached_version != current_version:
            logger.warning(
                "Cache invalidated: functualize version changed "
                "(cached=%r, current=%r)",
                cached_version,
                current_version,
            )
            return True

        cached_python = data.get("python_version")
        current_python = platform.python_version()
        if cached_python != current_python:
            logger.warning(
                "Cache invalidated: Python version changed (cached=%r, current=%r)",
                cached_python,
                current_python,
            )
            return True

        cached_deps_hash = data.get("deps_hash")
        current_deps_hash = compute_deps_hash(self._project_root)
        if cached_deps_hash != current_deps_hash:
            logger.warning(
                "Cache invalidated: dependencies hash changed (cached=%r, current=%r)",
                cached_deps_hash,
                current_deps_hash,
            )
            return True

        # A provider that does not know its discovery config cannot judge the
        # cached fingerprint; skip rather than assert the empty config.
        if self._discovery_hash is not None:
            cached_discovery_hash = data.get("discovery_hash")
            if cached_discovery_hash != self._discovery_hash:
                logger.warning(
                    "Cache invalidated: discovery config changed "
                    "(cached=%r, current=%r)",
                    cached_discovery_hash,
                    self._discovery_hash,
                )
                return True

        return False

    @staticmethod
    def _delete_cache_file(cache_path: str) -> None:
        """Delete a stale cache file from disk. Logs warning on failure."""
        try:
            Path(cache_path).unlink(missing_ok=True)
        except OSError as e:
            logger.warning("Failed to delete cache file %s: %s", cache_path, e)

    # =========================================================================
    # Statistics
    # =========================================================================

    def stats(self) -> CacheInfo:
        """Return cache statistics (entry count, stale count, file size, path).

        Staleness is a Tier 1 (mtime) check only — cheap and side-effect free.
        """
        stale_count = 0
        for entry in self._entries.values():
            try:
                current_mtime = os.path.getmtime(entry.source_file)
                if current_mtime != entry.source_mtime:
                    stale_count += 1
            except (FileNotFoundError, OSError):
                stale_count += 1

        file_size = 0
        cache_path: Path | None = None
        resolved = self._locator.resolve_one(CACHE_FILENAME)
        if resolved is not None:
            try:
                p = Path(resolved)
                file_size = p.stat().st_size
                cache_path = p
            except (FileNotFoundError, OSError):
                cache_path = None

        return CacheInfo(
            entry_count=len(self._entries),
            stale_count=stale_count,
            file_size_bytes=file_size,
            cache_path=cache_path,
        )

    # =========================================================================
    # Entry management
    # =========================================================================

    def _add_entry(self, descriptor: JobDescriptor) -> None:
        """Add a descriptor to both the entries dict and the name index."""
        key = f"{descriptor.source_file}::{descriptor.name}"
        self._entries[key] = descriptor
        self._by_name[descriptor.name] = descriptor

    def _remove_entries_for_file(self, source_file: str) -> None:
        """Remove all entries (jobs, displays, group options) for a source file."""
        keys_to_remove = [
            key
            for key, entry in self._entries.items()
            if entry.source_file == source_file
        ]
        for key in keys_to_remove:
            entry = self._entries.pop(key)
            # Remove from name index if it still points to this entry
            if self._by_name.get(entry.name) is entry:
                del self._by_name[entry.name]
        if source_file in self._display_entries:
            del self._display_entries[source_file]
            self._dirty = True
        # Group options are keyed by group path, so the file's entries are
        # found by scanning values rather than a single key lookup.
        stale_groups = [
            group
            for group, spec in self._group_options_entries.items()
            if spec.source_file == source_file
        ]
        for group in stale_groups:
            del self._group_options_entries[group]
            self._dirty = True

    def _known_source_files(self) -> set[str]:
        """Return the set of source file paths currently in the cache.

        Includes display-only and group-options-only files so an unchanged
        module that defines no jobs is validated, not re-imported, on each
        cycle. The conventional home for a group-options declaration
        (``jobs/deploy/_group.py``) is exactly such a job-free module.
        """
        files = {entry.source_file for entry in self._entries.values()}
        files.update(self._display_entries.keys())
        files.update(
            spec.source_file
            for spec in self._group_options_entries.values()
            if spec.source_file
        )
        return files

    # =========================================================================
    # Tiered validation
    # =========================================================================

    def _is_entry_valid(self, entry: JobDescriptor) -> bool:
        """Validate a cache entry using Tier 1 (mtime) + Tier 2 (sha256).

        Tier 1: If current file mtime matches entry.source_mtime → VALID.
        Tier 2: If mtime differs but sha256 of content matches content_hash →
                update source_mtime in memory (replace entry, mark dirty), VALID.
        Both fail (or file missing) → INVALID.
        """
        try:
            current_mtime = os.path.getmtime(entry.source_file)
        except (FileNotFoundError, OSError):
            return False

        # Tier 1: mtime check
        if current_mtime == entry.source_mtime:
            return True

        # Tier 2: sha256 content hash check
        try:
            content = Path(entry.source_file).read_bytes()
        except (FileNotFoundError, OSError):
            return False

        current_hash = hashlib.sha256(content).hexdigest()
        if current_hash == entry.content_hash:
            # Content unchanged despite mtime change — refresh mtime in memory
            updated = dataclasses.replace(entry, source_mtime=current_mtime)
            key = f"{entry.source_file}::{entry.name}"
            self._entries[key] = updated
            if self._by_name.get(entry.name) is entry:
                self._by_name[entry.name] = updated
            self._dirty = True
            return True

        return False

    def _is_entry_valid_deep(self, entry: JobDescriptor) -> bool:
        """Validate a cache entry using Tier 1 + Tier 2 + Tier 3 (dependencies).

        Tier 3: For each path in entry.dependencies, compute sha256 of the
        file and compare to the cached hash. If any dependency file is missing
        or its hash differs, returns False. If dependencies is empty, Tier 3
        passes vacuously.
        """
        if not self._is_entry_valid(entry):
            return False

        for dep_path, cached_hash in entry.dependencies.items():
            try:
                dep_content = Path(dep_path).read_bytes()
            except (FileNotFoundError, OSError):
                return False

            current_dep_hash = hashlib.sha256(dep_content).hexdigest()
            if current_dep_hash != cached_hash:
                return False

        return True

    def _validate_entries_for_file(self, source_file: str) -> bool:
        """Check if the entries for a source file are still valid (deep check).

        All entries for a file share source_mtime/content_hash, so validating
        one representative entry suffices. A file cached only for its
        displays (no job entries) is validated via its display entry, and one
        cached only for a group-options declaration via that spec.
        """
        for entry in list(self._entries.values()):
            if entry.source_file == source_file:
                return self._is_entry_valid_deep(entry)

        display_entry = self._display_entries.get(source_file)
        if display_entry is not None:
            return self._is_display_entry_valid(display_entry)

        for spec in list(self._group_options_entries.values()):
            if spec.source_file == source_file:
                return self._is_group_options_spec_valid(spec)

        # No entries for this file (shouldn't happen in normal flow)
        return False

    def _is_group_options_spec_valid(self, spec: GroupOptionsSpec) -> bool:
        """Tier 1 (mtime) + Tier 2 (sha256) validation for a group-options spec.

        Mirrors ``_is_display_entry_valid``: on a Tier 2 pass the mtime is
        refreshed in memory and the cache marked dirty.
        """
        try:
            current_mtime = os.path.getmtime(spec.source_file)
        except (FileNotFoundError, OSError):
            return False

        if current_mtime == spec.source_mtime:
            return True

        try:
            content = Path(spec.source_file).read_bytes()
        except (FileNotFoundError, OSError):
            return False

        if hashlib.sha256(content).hexdigest() == spec.content_hash:
            self._group_options_entries[spec.group] = dataclasses.replace(
                spec, source_mtime=current_mtime
            )
            self._dirty = True
            return True

        return False

    def _is_display_entry_valid(self, entry: DisplayCacheEntry) -> bool:
        """Tier 1 (mtime) + Tier 2 (sha256) validation for a display entry.

        Mirrors ``_is_entry_valid``: on a Tier 2 pass the mtime is refreshed
        in memory and the cache marked dirty.
        """
        try:
            current_mtime = os.path.getmtime(entry.source_file)
        except (FileNotFoundError, OSError):
            return False

        if current_mtime == entry.source_mtime:
            return True

        try:
            content = Path(entry.source_file).read_bytes()
        except (FileNotFoundError, OSError):
            return False

        if hashlib.sha256(content).hexdigest() == entry.content_hash:
            self._display_entries[entry.source_file] = dataclasses.replace(
                entry, source_mtime=current_mtime
            )
            self._dirty = True
            return True

        return False

    # =========================================================================
    # Module discovery and import
    # =========================================================================

    def _discover_module_files(self) -> set[str]:
        """Scan configured directories for Python module files (no imports).

        Returns absolute file paths for all discovered non-package modules.
        """
        on_disk: set[str] = set()

        for dir_path in self._directories:
            path = Path(dir_path)
            if not path.is_dir():
                continue
            try:
                for _importer, module_name, is_pkg in pkgutil.iter_modules([dir_path]):
                    if is_pkg:
                        continue
                    candidate = path / f"{module_name}.py"
                    if candidate.is_file():
                        on_disk.add(str(candidate.resolve()))
            except Exception as e:
                logger.warning("Failed to enumerate modules in '%s': %s", dir_path, e)

        return on_disk

    def _should_import(self, source_file: str) -> bool:
        """Apply pre-filter to decide if a module should be imported.

        Returns True if no pre-filter is configured or if the filter passes.
        This method does NOT use the pre-filter decision cache — it always
        runs the actual pre-filter. Used during get_job(name) targeted discovery
        (Requirement 19.7: bypass pre-filter cache for get_job calls).
        """
        if self._pre_filter is None:
            return True
        try:
            return self._pre_filter.should_import(Path(source_file))
        except Exception as e:
            logger.warning("Pre-filter raised exception for '%s': %s", source_file, e)
            return False

    def _should_import_with_cache(self, source_file: str) -> bool:
        """Apply pre-filter with decision caching for list_jobs() flow.

        Checks the pre-filter decision cache before running the actual pre-filter.
        Persists negative decisions to avoid repeated AST parses across restarts.

        Returns True if the module should be imported.
        """
        if self._pre_filter is None:
            return True

        # Check cached decision
        decision = self._pre_filter_decisions.get(source_file)
        if decision is not None:
            # Validate via mtime
            try:
                current_mtime = os.path.getmtime(source_file)
            except (FileNotFoundError, OSError):
                # File gone — remove stale decision
                del self._pre_filter_decisions[source_file]
                self._dirty = True
                return False

            if current_mtime == decision.source_mtime:
                # Mtime matches: use cached negative decision
                return decision.eligible  # Always False for persisted decisions
            else:
                # Mtime differs: re-run the pre-filter
                del self._pre_filter_decisions[source_file]
                self._dirty = True

        # Run the actual pre-filter
        try:
            result = self._pre_filter.should_import(Path(source_file))
        except Exception as e:
            logger.warning("Pre-filter raised exception for '%s': %s", source_file, e)
            return False

        # Persist negative decisions only (Requirement 19.2)
        if not result:
            try:
                mtime = os.path.getmtime(source_file)
            except (FileNotFoundError, OSError):
                return False
            self._pre_filter_decisions[source_file] = PreFilterDecision(
                source_file=source_file,
                eligible=False,
                source_mtime=mtime,
            )
            self._dirty = True

        return result

    def _safe_import(self, source_file: str) -> list[JobDescriptor]:
        """Import a module and extract job descriptors. Silent on failure.

        Also records the module's display-provider classes into the display
        section as a side effect of the same import pass.
        """
        try:
            from functualize._discovery.sync import extract_module

            extraction = extract_module(source_file, self._project_root)
        except Exception as e:
            logger.warning("Failed to import and extract from '%s': %s", source_file, e)
            return []

        self._record_display_entry(source_file, extraction)
        self._record_group_options_entries(source_file, extraction)
        return extraction.jobs

    def _record_group_options_entries(self, source_file: str, extraction: Any) -> None:
        """Sync the group-options section with what an import pass just found.

        Raises:
            GroupOptionsConflictError: Another module already declares one of
                these group paths.
        """
        # Drop this file's previous bindings first, so a declaration that was
        # renamed or removed does not linger, and so re-scanning the *same*
        # file never looks like a conflict with itself.
        for group in [
            group
            for group, spec in self._group_options_entries.items()
            if spec.source_file == source_file
        ]:
            del self._group_options_entries[group]
            self._dirty = True

        for spec in extraction.group_options:
            existing = self._group_options_entries.get(spec.group)
            if existing is not None and existing.source_file != source_file:
                raise GroupOptionsConflictError(
                    spec.group, existing.source_file, source_file
                )
            if existing != spec:
                self._group_options_entries[spec.group] = spec
                self._dirty = True

    def _record_display_entry(self, source_file: str, extraction: Any) -> None:
        """Sync the display section with what an import pass just found."""
        if extraction.display_classes:
            entry = DisplayCacheEntry(
                source_file=source_file,
                class_names=tuple(extraction.display_classes),
                source_mtime=extraction.source_mtime,
                content_hash=extraction.content_hash,
            )
            if self._display_entries.get(source_file) != entry:
                self._display_entries[source_file] = entry
                self._dirty = True
        elif source_file in self._display_entries:
            del self._display_entries[source_file]
            self._dirty = True

    def _targeted_discovery(self, name: str) -> JobDescriptor | None:
        """Attempt to find a job by name via targeted module discovery.

        Scans directories for a file whose stem matches the job name,
        imports it, adds discovered jobs to cache, and returns the match.

        NOTE: Pre-filter decision cache is BYPASSED during get_job(name) calls
        (Requirement 19.7). The raw _should_import method is used instead of
        _should_import_with_cache.

        Job names are canonical (`test-suite`) but *file* names are Python
        module names (`test_suite.py`), so the stem probe tries both spellings.
        Probing only the canonical form would make targeted discovery unable to
        find any job whose name contains a hyphen — which, after normalization,
        is every multi-word job.
        """
        stems = {name, name.replace("-", "_")}
        for dir_path in self._directories:
            path = Path(dir_path)
            if not path.is_dir():
                continue

            # Look for a module file whose stem matches the job name
            candidate = next(
                (
                    path / f"{stem}.py"
                    for stem in stems
                    if (path / f"{stem}.py").is_file()
                ),
                path / f"{name}.py",
            )
            if candidate.is_file():
                source_file = str(candidate.resolve())
                if not self._should_import(source_file):
                    return None
                descriptors = self._safe_import(source_file)
                for desc in descriptors:
                    self._add_entry(desc)
                if descriptors:
                    self._persist_cache()
                return self._resolve_entry(name)

        # Also scan all module files for multi-function modules
        # where the function name differs from the file stem
        on_disk = self._discover_module_files()
        cached_files = self._known_source_files()
        new_files = on_disk - cached_files

        for source_file in new_files:
            # Bypass pre-filter cache during get_job() (Requirement 19.7)
            if not self._should_import(source_file):
                continue
            descriptors = self._safe_import(source_file)
            for desc in descriptors:
                self._add_entry(desc)
            # Check if we found the target
            found = self._resolve_entry(name)
            if found is not None:
                self._persist_cache()
                return found

        # Not found anywhere
        return None

    def _resolve_entry(self, name: str) -> JobDescriptor | None:
        """Look up a descriptor by name, then by its canonical form."""
        descriptor = self._by_name.get(name)
        if descriptor is not None:
            return descriptor

        from functualize._types.naming import normalize_segment

        canonical = ".".join(normalize_segment(part) for part in name.split("."))
        return self._by_name.get(canonical) if canonical != name else None
