# SadlerACME 1.0.0-1 — Public Beta 1

**First public-beta release. Original project by Shane Sadler.**

Let's Encrypt wildcard and multi-domain certificates for Synology DSM using Cloudflare DNS. **Cloudflare DNS is required.**

## Included in this release

- Wildcard, ordinary hostname and multi-domain/SAN certificate configuration through Cloudflare DNS-01.
- A guided setup and recovery wizard with separate staging and production actions.
- DSM certificate deployment, renewal checks and managed background processing.
- Recovery backup and restore, uninstall preparation and an assembled administrator SSH recovery helper.
- Dashboard, direct Certificate settings, Automation, Backup & Restore, Uninstall, Logs and Help & About.
- Light and dark themes, remembered DSM window geometry, and separately scrolling wizard/log areas.
- Version-independent README and QuickStart, current installed help, and an illustrated installation/interface guide.

The package version, application version and installed help identify **1.0.0-1**. The package is marked as a beta; the GitHub release should be labelled **pre-release**, not stable.

## Platform scope

The package declares **x86_64** and a minimum of **DSM 7.0-40000**. It is intended for Synology NAS systems running DSM 7.0 or later on Intel/AMD x86_64 processors. It is not an ARM package. A declared installation minimum is not certification of every DSM point release or every model. Additional compatible models are welcome in the beta; unofficial DSM installations are not officially supported.

## Installation and upgrades

Install `SadlerACME-1.0.0-1.spk` through **Package Center → Manual Install**. For an existing installation, update while idle without uninstalling. Refresh DSM and reopen SadlerACME after the update.

The exact public-release installer was successfully upgraded over the accepted development build on the DSM lab. SadlerACME opened as **1.0.0-1**, preserved the existing certificate configuration, retained a verified DSM certificate match/default state, retained automatic six-hour renewal and active scheduler/queue/timer state, and retained the configured Cloudflare token. QuickStart, Workflow and Recovery all opened from **Help & About** with the **1.0.0-1** banner.

This release promotion changes release metadata, documentation and one legacy-task explanatory sentence. It does not change the accepted launcher, certificate engine, workflow controller, scheduler bridge, renewal units or package lifecycle implementation. Another certificate issuance is not required merely to install this release.

## Validation and limits

The release validation document distinguishes checks run on this exact package from earlier native acceptance of the unchanged implementation. Earlier production, staging, renewal-check, backup/recovery and removal observations are inherited evidence, not fresh end-to-end tests of this exact release artifact.

The final non-destructive native installation/open/help smoke test **passed**. Naturally due unattended renewal over time, DSM updates, additional genuine Synology models and emergency scheduler-API paths are not universally certified. Non-due renewal checks do not establish a naturally due renewal. Very small or highly zoomed desktops can exceed the practical usable window area. Keep normal NAS backups and an alternative means of accessing DSM.

## Release assets

- `SadlerACME-1.0.0-1.spk`: installer.
- `SadlerACME-1.0.0-1-source.zip`: corresponding source, pinned vendor material and offline tests.
- `SadlerACME-1.0.0-1-public-beta.zip`: complete public-beta bundle.
- `SadlerACME-Installation-and-Interface-Guide-1.0.0-1.docx`: illustrated guide; original screenshots may display an earlier version.
- `SadlerACME-1.0.0-1-SHA256SUMS.txt`: checksums for supplied release files.
- `SadlerACME-1.0.0-1-Validation.md`: exact-package checks, evidence boundaries and native smoke-test result.

Read `QUICKSTART.md`, `WORKFLOW.md` and `RECOVERY.md` before setup or recovery. Do not upload tokens, DSM passwords, private keys or recovery backups to issue reports.

## Licence

SadlerACME's original files are **GPL-3.0-only**. Original project by Shane Sadler. Bundled components retain their upstream notices and versions; see LICENSE, NOTICE.txt and vendor/NOTICE.md. The package is not endorsed by Synology, Cloudflare or the acme.sh project.
