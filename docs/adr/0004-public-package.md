# 0004. Publish ASM with a pinned HTTPS marketplace source

- Status: accepted
- Date: 2026-11-09
- Authority: explicit user request to make ASM public and update bardak's README.
- Supersedes: [0003](0003-bardak-marketplace.md).

## Context
ADR0003 kept the package private behind a public catalog entry, requiring
repository access to install it. The user has explicitly chosen public access.
Acceptance records that decision; it does not establish that GitHub visibility
or the catalog has already changed.

## Decision
Make `bahadirkisbet/asm` public. Keep `asm@bardak` and its `git-subdir` source
pointing to `plugins/asm`, using `https://github.com/bahadirkisbet/asm.git` and a
pinned commit. Update the public installation documentation accordingly.

Retain [0002](0002-git-marketplace.md)'s bundled native binaries and offline
startup, and [0001](0001-secret-boundary.md)'s credential boundary. Local operation
configuration and OS credentials remain outside the repository and plugin cache;
public package access grants no provider permissions or credential access.

## Options considered
- Keep the private package: rejected by the user's explicit publication decision.
- Public package with pinned HTTPS source: chosen to remove private Git access
  from installation while retaining a specific package revision.

## Consequences
Source, bundled binaries and repository history become publicly accessible;
making the repository private later cannot recall downloaded copies. Releases
still publish the package before updating bardak's commit pin. Checksums detect
damaged bundles, not a malicious publisher, as recorded in ADR0002.

## Verification
Planned: verify public GitHub visibility, anonymous HTTPS access to the pinned
commit, and the catalog's `git-subdir` path and pin. Check documentation consistency
and package integrity. This record does not claim publication or installation
verification has passed.
