# Releasing

Releases are built **on a maintainer's machine** and published as files of a GitHub release. GitHub doesn't build anything; it only hosts the files.

## What a release contains

| File | For |
| --- | --- |
| `synalchemy-<v>-py3-none-any.whl` | `pip install` |
| `synalchemy-<v>.tar.gz` | the source distribution |
| `SHA256SUMS` | checksums of both |

## Cut a release

1. Make sure `main` is clean and green (lint and tests; see [Testing](testing.md)).
2. Set `__version__` in `src/synalchemy/__init__.py`.
3. Add a `## [X.Y.Z]` section to `CHANGELOG.md`, and commit both.
4. Run the script:

   ```bash
   scripts/release.sh 0.2.0 --dry-run    # optional: checks, tests and build only; look at dist/
   scripts/release.sh 0.2.0
   ```

The script checks the tree, the tag, the version and the changelog. It then runs ruff and pytest, builds `dist/` with `uv build`, and validates it with `twine check`. Finally it tags `v0.2.0`, pushes `main` and the tag, and creates the GitHub release, with the changelog section plus install instructions as notes.

- A version with a suffix, such as `0.3.0-rc.1`, becomes a **prerelease**.
- `--draft` publishes a draft to check before announcing; `--skip-tests` skips lint and tests.

You need `uv`, and `gh` signed in with permission to create releases.

## Versions

SynAlchemy follows [semantic versioning](https://semver.org). Until 1.0, minor versions may break things, and the changelog says how to upgrade.
