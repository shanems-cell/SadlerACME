# Release guide — SadlerACME 1.0.0-1

**Public Beta 1. Original project by Shane Sadler.**

## Release identity

Use `1.0.0-1` for the SPK version, application display, release tag and versioned artifact names. Use the title **SadlerACME 1.0.0-1 — Public Beta 1** and mark the release as a pre-release. The package metadata contains `beta="yes"`.

README and QuickStart remain version-independent. Release-specific information belongs in CHANGELOG, RELEASE-NOTES and VALIDATION. Installed help is generated from QUICKSTART.md, WORKFLOW.md and RECOVERY.md.

## Build

On Linux with Python 3 and GNU tar:

```sh
sh build-spk.sh
```

Build output is written under `dist/`. Worker modules and the recovery helper are assembled before packaging. Vendor material is pinned.

## Final verification

Check the exact-package validation record, package/source correspondence, allowed-change comparison, syntax and offline regression results. Regenerate SHA-256 checksums after all release files are final.

Do not replace an already distributed installer with different bytes under the same version; use a new build identifier for a changed installer.

## Native publication gate — passed

The exact `SadlerACME-1.0.0-1.spk` installer was upgraded over the accepted idle DSM lab installation without uninstalling. The application reopened as **1.0.0-1**, retained its existing verified/default DSM certificate state and renewal automation, and the three installed Help & About guides opened with the correct version banner.

This gate is complete. No staging, issuance, forced renewal, backup or removal retest is required solely for this metadata/documentation promotion.

## GitHub publication

Repository: `https://github.com/shanems-cell/SadlerACME`

Create tag `v1.0.0-1` from `main`. Release title:

**SadlerACME 1.0.0-1 — Public Beta 1**

Mark the release as **Pre-release**.

Upload the exact installer, corresponding source archive, public-beta bundle, checksums, release notes, validation record and illustrated guide. Verify the uploaded SPK SHA-256 remains:

`4220114fe2ed523ac7cd222abdc2ecdd0822fb045fb66878f2c37c3232f34d12`

## Reports and support

Ask for model, architecture, DSM version, package version, installation route, attempted action, exact error and relevant redacted log lines. Never request passwords, API tokens, private keys or recovery backups in public reports.
