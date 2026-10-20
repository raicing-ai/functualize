# External contracts — project root boundary

## Existing configuration input

| Surface | Contract |
| --- | --- |
| Project file `root = true` | The file is included; upward project discovery stops at its directory for all project-resolved sources. |
| `jobs_directories`, `import_libs`, `plugins_directories`, `extra_directories` | Declarations in active project layers retain their list order and path resolution. Declarations in project layers above the root do not contribute. |
| Explicit path outside the root | An active project layer may intentionally name it. The boundary does not reject it. |
| CLI and environment overrides | Continue to outrank project file sources. |
| XDG user configuration | Continues to apply as a global source independent of the project root. |

## Existing output and command surfaces

| Surface | Contract |
| --- | --- |
| `func <job>` | A job supplied only by an ancestor excluded by `root = true` is an unknown command, with the existing nonzero exit and error form. |
| `func builtin info jobs --json` | The job-name array excludes jobs supplied only by excluded ancestor project sources. The JSON shape does not change. |
| `func builtin info` | Reported project mode and loaded source inventory describe the same bounded project. Existing text and JSON shapes remain unless architecture work proves a necessary change. |
| `func builtin config path` | Shows active project config layers and does not mark an excluded ancestor project file as used. Existing output shape remains. |
| `func --help` and other command inventories | Do not advertise a job supplied only by an excluded ancestor project source. |

## Compatibility

The intended behavior corrects an existing leak for projects that both set `root = true` and rely on inherited ancestor sources. The release note gives two migration choices: remove the root marker to inherit, or keep it and declare the shared path explicitly. No new external signature or payload is proposed.
