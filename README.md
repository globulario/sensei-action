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

No permanent webhook server, VPS, external database, or provider-specific model
API key is required for this first product version.

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

### Configure GitHub Models inference

For a standalone organization whose repository `GITHUB_TOKEN` receives an HTTP
`403` from GitHub Models, create a fine-grained personal access token under the
maintainer's personal account with only **Account permissions → Models:
Read-only**. Store it as the repository Actions secret:

```text
SENSEI_MODELS_TOKEN
```

Pass that secret to the reusable action through `models-token`. The personal
token is used only by `actions/ai-inference`; repository branch and pull-request
operations continue to use the workflow's temporary `GITHUB_TOKEN`.

Organizations with native GitHub Models enabled may omit `models-token`. The
action then falls back to `GITHUB_TOKEN`, provided the workflow grants
`models: read` and the organization/repository Models switches allow access.

A Models authorization failure occurs before Sensei sends the architectural
prompt. It therefore cannot partially mutate the repository.

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

# In the bootstrap step:
with:
  models-token: ${{ secrets.SENSEI_MODELS_TOKEN }}
```

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
| `model` | `openai/gpt-4.1` | GitHub Models model identifier. |
| `models-token` | workflow `GITHUB_TOKEN` | Optional token with Models read permission. |
| `sensei-ref` | `v1.1.0` | Pinned Sensei version. |
| `repository-root` | `.` | Checkout root. |
| `branch-prefix` | `sensei/bootstrap` | Prefix for generated branches. |
| `pr-title` | `chore: bootstrap Sensei architectural memory` | Draft PR title. |
| `max-context-bytes` | `180000` | Hard cap on repository context sent to the model. |
| `dry-run` | `false` | Validate without pushing a branch or creating a PR. |

### Maintainer live proof

The repository's **Bootstrap live smoke** workflow runs on relevant trusted
changes reaching `main`, and may also be started manually. It:

1. verifies a tiny GitHub Models request with `SENSEI_MODELS_TOKEN`
2. bootstraps an isolated Go fixture with the complete reusable action
3. checks the governed receipt and cryptographic digests
4. uploads the receipt, proposal, questions, invariants, and failure modes as a
   live-proof artifact

The secret-bearing smoke does not run for pull requests.

## Trust model

- Review runs may execute automatically because they use read-only repository
  access aside from optional result publication.
- Bootstrap runs are manual `workflow_dispatch` operations from the trusted
  default branch.
- The secret-backed live smoke runs only on trusted `main` or manual dispatch.
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
