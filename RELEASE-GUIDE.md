# Release guide — SadlerACME 1.0.0-1

**Public Beta 1. Original project by Shane Sadler.**

## Release identity

Use `1.0.0-1` for the SPK version, application display, release tag and versioned artifact names. Use the title **SadlerACME 1.0.0-1 — Public Beta 1** and mark the release as a pre-release. The package metadata contains `beta="yes"`. Do not replace an already distributed installer with different bytes under the same version; use a new build identifier for a changed installer.

README and QuickStart remain version-independent. Release-specific information belongs in CHANGELOG, RELEASE-NOTES and VALIDATION. Installed help is generated from QUICKSTART.md, WORKFLOW.md and RECOVERY.md, and carries the package version in its banner. Do not edit only generated HTML and leave the source stale.

## Build

On Linux with Python 3 and GNU tar:

```sh
sh build-spk.sh
```

Build output is written under `dist/`. Worker modules and the recovery helper are assembled before packaging. The raw source templates are not standalone privileged executables. Vendor material is pinned; do not update it as part of a metadata-only release.

## Final verification

Check the exact-package validation record, package/source correspondence, allowed-change comparison, syntax and offline regression results. Confirm that runtime functions, lifecycle scripts, worker/helper, scheduler bridge, vendor payload and renewal units were not changed by release preparation.

Regenerate SHA-256 checksums after all files are final. Reopen the archive and verify its manifest. The corresponding source archive must build the same payload; archive timestamp differences need not produce a byte-identical outer tarball.

## Native publication gate

Update the idle lab without uninstalling, then refresh DSM and reopen the application. Confirm **1.0.0-1**, beta metadata, the Cloudflare-focused package description and all three installed guides. Confirm that the installed recovery-help link still offers the helper download; its installed download filename is generic. The separately supplied release helper uses a versioned filename. This is a non-destructive installation/open/help check, not a request to repeat staging, issuance, renewal, backup or removal.

If Package Center refuses the version transition, preserve the installed package and report the message. Do not uninstall a configured installation merely to bypass a refused upgrade.

## Publish only after approval

Prepare a GitHub pre-release with the installer, source archive, checksums, recovery helper, illustrated guide and release notes. Verify that download links and reporting destinations point to the approved repository. No repository or publication URL is invented by this bundle; uploading and publishing are separate approved actions.

## Reports and support

Ask for model, architecture, DSM version, package version, installation route, attempted action, exact error and relevant redacted log lines. Never request passwords, API tokens, private keys or recovery backups in public reports. Use BETA-REPORT-TEMPLATE.md and TESTER-CHECKLIST.md for scoped feedback.
