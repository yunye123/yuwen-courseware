# Public-repository maintenance boundary

This is an independent public repository, not a branch, clone, worktree, submodule or mirror of the private development repository.

- The public repository contains only a reviewed allowlist and has its own `main` history and public `origin`.
- Never use `git push --mirror`, `git push --all`, `git bundle ... --all`, or a mirrored clone to publish it.
- New public changes are reviewed for copyright, privacy, secrets and machine paths before they enter this repository.
- Every bundled resource needs a documented owner, source and license that permits this repository's personal-learning distribution. If that evidence is missing, retain only a link or exclude the resource.
- Public fixes may inform private development, but are manually reviewed and reimplemented or cherry-picked only after checking the private repository's policy; no automatic bidirectional sync is allowed.
- A future public release is tagged only in this repository. Private alpha tags and private Git objects must never be pushed here.

## Maintainer workflow

Normal public changes use a short-lived `codex/<scope>` branch and a Draft PR. Do not push directly to `main`.

1. Start from a clean public checkout, update `main` with `git pull --ff-only origin main`, then create `codex/<scope>`.
2. Manually import only a reviewed public allowlist. Never copy a private `.git` directory, private history, textbooks, curriculum text, teacher cases, generated deliverables, benchmarks or local machine data.
3. Stage explicit paths only. Before committing, run the checks in [CONTRIBUTING.md](CONTRIBUTING.md), inspect the staged diff, and confirm that the allowlist and licensing evidence still match the change.
4. Push only the branch and open or update a Draft PR against `main`. A maintainer must explicitly review it before merge.

After a PR is merged, update local `main` from `origin/main`, create one annotated public tag on that merged commit, and push that tag explicitly. Never use `git push --tags`.

To recover a public regression, create `codex/revert-<scope>`, run `git revert <commit>`, validate it, and submit another PR. Do not rewrite `main`, force-push it, or move or recreate a published tag.
