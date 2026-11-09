# 0002. Self-contained plugin in the private Git marketplace

- Status: accepted
- Date: 2026-11-09

## Context
The user wants ASM installed as a Claude Code/Codex plugin from their own GitHub
marketplace. Plugin caches must work without the source checkout or a Rust compiler.

## Decision
The existing private repository carries both marketplace catalogs and one plugin
directory with client-specific manifests/MCP declarations, a shared skill and
launcher, and CI-built macOS arm64/x86_64 and Linux x86_64 binaries. SHA-256 hashes,
binary version and source commit travel with the bundle. Startup is offline.
The catalog is `bahadir-plugins`; the install identifier is `asm@bahadir-plugins`.

## Options considered
- Build at startup: adds Rust/toolchain dependencies and can exceed MCP timeouts.
- Download release assets at startup: adds private-repository auth and network
  failure paths to every fresh install.
- Bundle binaries in Git: chosen for predictable private-repo installation.

## Consequences
Git history grows by native executable updates. Checksums detect damaged bundles,
not a malicious publisher or modified trusted Git source. Source history and CI
provenance remain reviewable. Users authenticate to Git once; no new service is
required. Configuration and OS credentials remain outside plugin caches and
survive updates/removal. Python 3.9+ is the launch runtime; Rust is build-only.
