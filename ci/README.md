# Installing the CI workflow

`github-actions-ci.yml` is the complete GitHub Actions workflow for this repository. It is stored here because the automation that pushes to this repository is not permitted to write under `.github/workflows/` (GitHub answers `403 Resource not accessible`; both the GitHub App installation and the stored personal access token lack the **Workflows** permission).

**CI is not active until this file exists at `.github/workflows/ci.yml` and a run has succeeded.**

## Install it (about one minute, in the browser)

1. Open <https://github.com/Rationaloptimist140/Signal-Atlas-/new/main?filename=.github/workflows/ci.yml>
2. Paste the full contents of [`github-actions-ci.yml`](github-actions-ci.yml).
3. Choose **Commit changes** (directly to `main`).
4. Open the **Actions** tab: a run named **CI** starts. Both jobs (**Backend**, **Frontend**) should finish green.

After that, this `ci/` folder can be deleted.

## Or grant the permission

* **Personal access token (fine-grained):** edit the token → Repository access must include `Signal-Atlas-` → Repository permissions → **Workflows: Read and write** (and **Contents: Read and write**).
* **GitHub App installation:** the app must request the *Workflows* permission; if it does, approve the updated permissions under GitHub → Settings → Applications → Installed GitHub Apps.

## What the workflow checks

| Job | Steps |
|---|---|
| Backend | Ruff lint · tests on SQLite · the same tests on PostgreSQL 16 and Redis 7 · migrations up, drift check, down, up · `pip-audit` |
| Frontend | ESLint · TypeScript · Vitest · production build · `npm audit` (high and above) |

It runs on pull requests targeting `main` and on pushes to `main`. Every step has been run locally with the same commands and passes; the workflow itself has never run on GitHub.
