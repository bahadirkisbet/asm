# 0003. Publish the catalog in bardak, keep the package private

- Status: superseded by [0004](0004-public-package.md)
- Date: 2026-11-09

## Context
The user already maintains the public `bahadirkisbet/bardak` skills marketplace
and explicitly chose to list ASM there, with only its catalog entry public.

## Decision
Use `asm@bardak`. The shared Claude/Codex catalog in bardak points to
`plugins/asm` in the private ASM repository using a `git-subdir` source and a
pinned commit. Remove the separate marketplace catalogs from ASM. Keep all
implementation, binaries and package content in the private repository.

## Consequences
The public entry reveals ASM's name, description, version, repository address
and release commit, but grants no repository access. Installing requires an SSH
identity authorized for the private repository. Releases update the private
package first and then the public catalog's commit pin. Existing bardak skills
remain unchanged. Configuration and stored credentials do not move.
