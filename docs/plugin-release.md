# Releasing ASM through bardak

The private `bahadirkisbet/asm` repository holds the package in `plugins/asm`.
The public `bahadirkisbet/bardak` marketplace contains only its catalog entry,
using `git-subdir`, the standard SSH repository URL and a pinned commit. Never
copy ASM code/binaries into bardak. Never put user config, credentials, backups
or caches in the plugin folder. The demo config and runnable synthetic examples
are packaged alongside the logo; user-specific configuration is never copied.

1. Set matching versions in Cargo.toml and both plugin.json manifests; update
   Cargo.lock. Commit the source being built.
2. Dispatch `.github/workflows/plugin-binaries.yml` on that commit. It runs Rust
   tests and the release binary through MCP fixtures on macOS arm64, macOS Intel
   and Linux x86_64. Require all jobs to pass.
3. Download all three artifacts into a scratch directory, then run:

   ```sh
   python3 scripts/package_plugin.py target/plugin-artifacts --source-commit <built-sha>
   ```

   This verifies artifact versions, checksums and source identity before copying.
   It copies the demo config, runnable examples and license into the self-contained plugin.
4. Run repository checks, `python3 tests/plugin_e2e.py`,
   and `claude plugin validate plugins/asm`.
5. Commit the private plugin package and check the pushed commit's CI. Then update
   the ASM entry's version and commit pin in bardak, validate that marketplace
   with `claude plugin validate .`, and publish the catalog change.
   Native binaries are deliberately tracked for offline startup/private Git
   distribution; Git history grows with binary updates.
6. Test installing from the **Git URL** in each native client, inspect the loaded
   skill/MCP inventory, and verify catalog access from the installed cache.

The bundled logo is used by both client manifests. Public-directory submission,
publisher signing/notarization, Windows and Linux arm64 are outside this release.
