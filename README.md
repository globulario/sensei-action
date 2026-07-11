<p align="center">
  <img src="image/sensei-logo.png" alt="Sensei" width="160">
</p>

<h1 align="center">Sensei Architectural Review</h1>

<p align="center"><em>Review every pull request against your repository's architectural memory.</em></p>

Review every pull request against your repository's **architectural memory** —
the invariants, forbidden fixes, contracts, and required tests you keep with
[**Sensei**](https://github.com/globulario/sensei). The action resolves the two
runtime blockers for you (it fetches Oxigraph — no Docker — and runs the gRPC
server), evaluates the diff, and writes a Markdown summary into the Actions job
summary.

One line in your workflow:

```yaml
- uses: globulario/sensei-action@v1
  with:
    mode: advisory
```

## Quick start

Your repository must be a Sensei project — a committed `docs/awareness/`
directory. Create one once with `sensei init` or `sensei bootstrap --repo .`
(see the [Sensei docs](https://github.com/globulario/sensei)).

`.github/workflows/sensei.yml`:

```yaml
name: Sensei architectural review

on:
  pull_request:

permissions:
  contents: read
  security-events: write     # so findings appear in the Security tab (SARIF)

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0            # full history so the PR diff resolves

      - uses: globulario/sensei-action@v1
        with:
          mode: advisory            # advisory (report, never blocks) | enforce (fail on a violation)
```

## Inputs

| Input | Default | Description |
|---|---|---|
| `mode` | `advisory` | `advisory` reports findings and never blocks; `enforce` fails the check on a blocking finding (and fails **closed** if the diff can't be verified). |
| `awareness-dir` | `docs/awareness` | Directory holding your awareness YAML sources. |
| `diff` | *(auto)* | git diff range to review. Defaults to the PR `base...HEAD` (or the last commit on a push). |
| `domain` | *(none)* | Domain/repo scope, e.g. `github.com/you/yourrepo`. Only needed if your graph hosts more than one domain. |
| `sensei-ref` | `main` | Git ref of `globulario/sensei` to build the reviewer from (pin to a tag for reproducibility). |
| `go-version` | `1.25` | Go toolchain used to build Sensei. |

## What it does

1. Builds Sensei from `globulario/sensei@<sensei-ref>` and fetches Oxigraph.
2. Validates the awareness corpus (`sensei check`).
3. Starts the local store + gRPC server (`sensei serve`).
4. Compiles your `docs/awareness/` into the graph.
5. Reviews the PR diff (`sensei gate --mode <mode>`) and posts a Markdown summary.

Per-repo enforcement policy (`.sensei/gate-policy.yaml`) can re-level or silence
any rule with no code change.

## Code scanning (SARIF)

By default the action uploads findings to **GitHub code scanning**, so they appear
inline in the PR's *Files changed* view and under **Security → Code scanning**.
This needs `security-events: write` in the calling workflow (shown above). On
pull requests from forks, GitHub restricts this upload; the step is best-effort
and never fails the run. Disable with `sarif: false`.

## Notes

- **Pin `sensei-ref` to a tag** (e.g. `sensei-ref: v0.1.0`) for reproducible runs;
  `main` tracks the latest.
- The action builds Sensei from source (~30–40s). Prebuilt-binary installation
  will land once per-OS release binaries are published.
- Roadmap: SARIF output for GitHub code scanning, `ratchet` mode (fail only on
  *new* violations vs. a baseline), and `--fail-on <severity>`.

## License

Apache License, Version 2.0 — see [LICENSE](LICENSE). Sensei itself lives at
[globulario/sensei](https://github.com/globulario/sensei).
