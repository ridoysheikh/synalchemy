#!/usr/bin/env bash
# Cut a SynAlchemy release from this machine: check, test, build into dist/,
# tag the commit and publish the files as a GitHub release. GitHub only hosts
# the result; nothing is built there.
#
#   scripts/release.sh 0.1.0                # tests, build, tag, publish
#   scripts/release.sh 0.2.0-rc.1           # a prerelease
#   scripts/release.sh 0.1.0 --dry-run      # tests and build only
#
# Options:
#   --dry-run      build dist/ but do not tag or publish
#   --skip-tests   skip ruff and pytest
#   --draft        publish as a draft release
set -euo pipefail
cd "$(dirname "$0")/.."

REPO=${SYNALCHEMY_REPO:-ridoysheikh/synalchemy}
V=${1:-}; shift || true
V=${V#v}
DRY=0 TESTS=1 DRAFT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --skip-tests) TESTS=0 ;;
    --draft) DRAFT=--draft ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

die() { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }
step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

[[ "$V" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.]+)?$ ]] || die "usage: scripts/release.sh X.Y.Z[-pre] [options]"
TAG=v$V
# PEP 440 spelling of the version, as in the wheel name (0.2.0-rc.1 -> 0.2.0rc1)
PYV=$(echo "$V" | sed -E 's/-(a|alpha)\.?/a/; s/-(b|beta)\.?/b/; s/-rc\.?/rc/')

step "Checks"
command -v uv >/dev/null || die "uv is required"
[ -z "$(git status --porcelain)" ] || die "the working tree has changes; commit or stash them"
git rev-parse -q --verify "refs/tags/$TAG" >/dev/null && die "tag $TAG exists already"
code_v=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' src/synalchemy/__init__.py)
[ "$code_v" = "$PYV" ] || die "src/synalchemy/__init__.py has __version__ = \"$code_v\", expected \"$PYV\""
grep -q "^## \[$V\]" CHANGELOG.md || die "CHANGELOG.md has no \"## [$V]\" section"
if [ "$DRY" = 0 ]; then
  command -v gh >/dev/null || die "the GitHub CLI (gh) is required"
  gh auth status >/dev/null 2>&1 || die "gh is not signed in (gh auth login)"
  gh release view "$TAG" -R "$REPO" >/dev/null 2>&1 && die "release $TAG exists on GitHub already"
fi
echo "releasing $TAG from $(git rev-parse --short HEAD) on $(git rev-parse --abbrev-ref HEAD)"

if [ "$TESTS" = 1 ]; then
  step "Tests"
  uv run ruff check src tests
  uv run ruff format --check src tests
  uv run pytest -q
fi

step "Build"
rm -rf dist
uv build
uvx twine check dist/*
(cd dist && sha256sum ./*.whl ./*.tar.gz | sed 's| \./| |' > SHA256SUMS)
ls dist/"synalchemy-$PYV-py3-none-any.whl" >/dev/null || die "the wheel is not version $PYV"

# Release notes: the CHANGELOG section, then how to install.
notes=$(mktemp)
awk -v v="$V" 'index($0, "## [" v "]") == 1 {on=1; next} on && /^## \[/ {exit} on' CHANGELOG.md > "$notes"
cat >> "$notes" <<EOF

## Install

\`\`\`sh
pip install "synalchemy[postgres] @ https://github.com/$REPO/releases/download/$TAG/synalchemy-$PYV-py3-none-any.whl"
\`\`\`

Pick the extras you need: \`postgres\`, \`postgres-sync\`, \`mysql\`, \`sqlite\`, \`mssql\`, \`oracle\`.
Docs: https://github.com/$REPO/tree/$TAG/docs. Checksums are in \`SHA256SUMS\`.
EOF

if [ "$DRY" = 1 ]; then
  step "Dry run: dist/ is ready; not tagging or publishing"
  cat "$notes"; rm -f "$notes"; exit 0
fi

step "Tag and publish"
pre=""; case "$V" in *-*) pre=--prerelease ;; esac
git tag -a "$TAG" -m "SynAlchemy $TAG"
git push origin HEAD "$TAG"
gh release create "$TAG" -R "$REPO" --verify-tag --title "SynAlchemy $TAG" --notes-file "$notes" $pre $DRAFT dist/*
rm -f "$notes"
echo
echo "Published https://github.com/$REPO/releases/tag/$TAG"
