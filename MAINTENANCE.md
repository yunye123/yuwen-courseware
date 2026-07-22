# Public-repository maintenance boundary

This is an independent public repository, not a branch, clone, worktree, submodule or mirror of the private development repository.

- The public repository contains only a reviewed allowlist and has its own `main` history and public `origin`.
- Never use `git push --mirror`, `git push --all`, `git bundle ... --all`, or a mirrored clone to publish it.
- New public changes are reviewed for copyright, privacy, secrets and machine paths before they enter this repository.
- Every bundled resource needs a documented owner, source and license that permits this repository's personal-learning distribution. If that evidence is missing, retain only a link or exclude the resource.
- Public fixes may inform private development, but are manually reviewed and reimplemented or cherry-picked only after checking the private repository's policy; no automatic bidirectional sync is allowed.
- A future public release is tagged only in this repository. Private alpha tags and private Git objects must never be pushed here.
