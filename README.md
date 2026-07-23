<p align="center">
  <img src="image/sensei-logo.png" alt="Sensei" width="160">
</p>

<h1 align="center">Sensei for GitHub Actions</h1>

<p align="center"><em>Review every pull request, then bootstrap architectural memory without operating a backend.</em></p>

Sensei runs entirely on GitHub-hosted Actions runners. The repository remains the
source of truth, the runner is temporary, and every generated result is attached
to an exact Git revision.

This repository provides two bounded workflows:

1. **Architectural review** evaluates a pull-request diff against committed
   invariants, failure modes, contracts, and required tests.
2. **AI-assisted bootstrap** runs deterministic Sensei extraction first, asks a
   GitHub Models model for a small evidence-grounded candidate corpus, validates
   it with Sensei, and opens a draft PR for human review.

No permanent webhook server, VPS, external database, or separate model API key is
required for this first product version.

## Pull-request review

Add `.github/workflows/sensei.yml` to a Sensei-enabled repository:

```yaml
name: Sensei architectural review

on:
  pull_request:

permissions:
  contents: read
  security-events: write

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: globulario/sensei-action@v1
        with:
          mode: advisory
          sensei-ref: v1.1.0
```

The review action:

1. installs the pinned Sensei bundle, with a source-build fallback
2. validates `docs/awareness/`
3. starts the local Oxigraph store and awareness gRPC server
4. compiles the repository graph
5. reviews the exact PR diff
6. publishes a job summary and optional SARIF findings

### Review inputs

| Input | Default | Description |
|---|---|---|
| `mode` | `advisory` | `advisory` reports findings without blocking; `enforce` fails on blocking findings and fails closed when the diff cannot be verified. |
| `awareness-dir` | `docs/awareness` | Directory containing awareness YAML. |
| `diff` | auto | Explicit git diff range. |
| `domain` | none | Optional domain/repository scope. |
| `sarif` | `true` | Upload findings to GitHub code scanning when permitted. |
| `sensei-ref` | `v1.1.0` | Pinned Sensei release, branch, or commit. |
| `go-version` | `1.25` | Go version for the fallback source build. |

## AI-assisted bootstrap

### Enable GitHub Models first

For an organization-owned repository, an organization owner must enable GitHub
Models under **Organization Settings → Models → Development**. A repository
administrator must then enable it under **Repository Settings → Models**. The
workflow permission `models: read` grants the job access only after both feature
switches allow it.

A disabled organization or repository currently appears in Actions as an
`actions/ai-inference` HTTP `403` with no response body. No Sensei code or model
prompt has executed when that preflight fails.

### Allow the bootstrap workflow to create its draft PR

Under **Repository Settings → Actions → General → Workflow permissions**, enable
**Allow GitHub Actions to create and approve pull requests**. Sensei only uses
that capability to push a new bootstrap branch and open a draft PR. It never
commits directly to the default branch.

A pull request created by the repository's temporary `GITHUB_TOKEN` may place its
own workflows in an approval-required state. A maintainer with write access can
approve those checks from the PR. A later GitHub App installation token can
remove that small manual seam without moving Sensei's compute off GitHub-hosted
runners.

Copy [`examples/sensei-bootstrap.yml`](examples/sensei-bootstrap.yml) into the
target repository as `.github/workflows/sensei-bootstrap.yml`. Commit it to the
default branch, open the **Actions** tab, choose **Bootstrap Sensei architectural
memory**, and select **Run workflow**.

The calling workflow requires:

```yaml
permissions:
  contents: write
  pull-requests: write
  models: read
```

Once Models is enabled, GitHub Models runs with the workflow's temporary
`GITHUB_TOKEN`; no OpenAI or Anthropic secret is required.

### Bootstrap execution contract

```text
trusted default branch
        ↓
deterministic sensei bootstrap --skip-history
        ↓
bounded repository context
        ↓
GitHub Models candidate draft
        ↓
force every model claim to review_only
        ↓
strict parser + fixed writable paths
        ↓
sensei check + bootstrap freshness check
        ↓
one repair attempt when validation fails
        ↓
draft pull request
```

The model is not a shell agent. It cannot edit source code or choose arbitrary
paths. It may only:

- populate `docs/awareness/invariants.yaml` when that starter corpus is empty
- populate `docs/awareness/failure_modes.yaml` when that starter corpus is empty
- write `docs/awareness/BOOTSTRAP_QUESTIONS.md`
- write proposal and proof receipts under `.sensei/`

An established invariant or failure-mode corpus is never overwritten. Every
model-authored invariant and failure mode is normalized to `review_only`, even if
the model proposes `active` or `fixed`. Human promotion is a separate governed
act. The model gets at most two attempts, and every accepted result must pass
Sensei validation. All changes land in a draft PR rather than on the default
branch.

### Bootstrap inputs

| Input | Default | Description |
|---|---|---|
| `base-branch` | required | Base branch for the draft PR. |
| `model` | `openai/gpt-4o` | GitHub Models model identifier. |
| `sensei-ref` | `v1.1.0` | Pinned Sensei version. |
| `repository-root` | `.` | Checkout root. |
| `branch-prefix` | `sensei/bootstrap` | Prefix for generated branches. |
| `pr-title` | `chore: bootstrap Sensei architectural memory` | Draft PR title. |
| `max-context-bytes` | `180000` | Hard cap on repository context sent to the model. |
| `dry-run` | `false` | Validate without pushing a branch or creating a PR. |

### Maintainer live proof

After enabling GitHub Models for the organization and this repository, run
**Bootstrap live smoke** from the Actions tab. It first performs a tiny model
preflight, then runs the complete bootstrap Action in dry-run mode against an
isolated Go fixture repository.

## Trust model

- Review runs may execute automatically because they use read-only repository
  access aside from optional result publication.
- Bootstrap runs are manual `workflow_dispatch` operations from the trusted
  default branch.
- Bootstrap write permissions are used only to push a new branch and open a
  draft PR.
- Model output is untrusted input until normalized, parsed, path-restricted, and
  validated by Sensei.
- The model response digest, bounded context digest, source revision, accepted
  attempt, and written-file digests are represented in bootstrap receipts.

## Local development

```bash
python -m unittest discover -s bootstrap/tests -v
bash -n bootstrap/scripts/install-sensei.sh
```

## License

Apache License, Version 2.0. Sensei lives at
[globulario/sensei](https://github.com/globulario/sensei).
