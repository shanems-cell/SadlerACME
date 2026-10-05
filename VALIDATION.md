# SadlerACME 1.0.0-1 — release validation

**Public Beta 1 release candidate. Local release checks and the final native installation/open/installed-help smoke test are complete.**

Original project by Shane Sadler. Prepared 5 October 2026.

## Release boundary

This is a documentation and metadata promotion of the accepted development implementation. Earlier native results remain earlier results; they have not been renamed as newly executed tests of this exact installer. Historical reports remain with the original development materials, outside the public release bundle.

Accepted development installer SHA-256:

`26e6cc18e79279d9b000333dddac49f6999d2104c602d685ca2e90c54c6cbd50`

Final release installer SHA-256:

`4220114fe2ed523ac7cd222abdc2ecdd0822fb045fb66878f2c37c3232f34d12`

## Exact package comparison

The payload file set and file modes remain unchanged. Exactly four payload files differ from the accepted installer: the three generated guides (`ui/QUICKSTART.html`, `ui/WORKFLOW.html`, `ui/RECOVERY.html`) and `ui/index.cgi`.

The CGI difference is limited to the version display and one legacy-task explanatory sentence that no longer names an obsolete release. After normalising those two strings, the assembled CGI is byte-identical. INFO changes are limited to version, the Cloudflare/wildcard/multi-domain description, and `beta="yes"`.

The launcher, both stylesheets, workflow/theme JavaScript, scheduler/authentication bridge, privileged certificate worker, emergency helper, all ten systemd units, lifecycle scripts, privileges, icons, licences and pinned vendor implementation are unchanged. No certificate issuance, renewal, recovery or uninstall logic was modified.

Protected hashes:

- Certificate worker: `3c1fb6d1edbcd1cfec4701684e398255bea3c2d753d9f8096fa2e0f1a1c5c927`
- Emergency helper: `fff8b068aaf5d9b8242b5d20c93ab7a7bfc53ec3e7063634ac649e134c3dc4b5`

`tests/RESULTS-1.0.0-1-package.json` records the allowed changes, complete payload hashes, modes, ownership and protected-file identity.

## Local checks actually run

| Check | Result |
| --- | --- |
| Python regression/workflow/scheduler/status suites | 214 unittest cases passed across 10 suites |
| Window sizing | 17/17 fixtures passed |
| Window placement: self-contained model | 38/38 scenarios passed |
| Same placement scenarios with selected supplied DSM definitions | 38/38 passed; DOM/base rendering remains simulated |
| Theme UI | 13/13 fixtures passed |
| Temporary-worker UI | 20/20 fixtures passed |
| Workflow UI | Existing full suite passed; no invented numeric count |
| Rendered CGI/UI browser checks | 258/258 passed |
| Wizard scrollbar clearance/hit targets | 84/84 passed |
| Selected enabled-text contrast pairs | 44/44 passed; not a full accessibility audit |
| Syntax, configuration and image assets | Passed |
| Installed-help rendering | Six wide/narrow guide-layout cases passed |
| Public documentation and installed-help integrity | Passed |
| Illustrated guide | Eleven rendered pages visually reviewed; original selected screenshots retained |
| Source rebuild and release-archive checksums | Passed |

The two placement runs exercise the same 38 scenarios in different harnesses, not 76 independent native tests. Tests use temporary filesystems, synthetic configuration and mocked or intercepted DSM/ACME boundaries unless explicitly stated otherwise.

## Documentation and screenshot treatment

README and QuickStart remain release-version-independent. Current written public documents and installed guides use generic wording or **1.0.0-1**, without obsolete SadlerACME release references.

The installed guides are regenerated from their Markdown source. Their banners identify **SadlerACME 1.0.0-1 — Public Beta**.

Original documentation screenshots retain their captured version labels, as approved. They illustrate the unchanged interface and are not presented as new native acceptance of this release. Help & About uses the replacement image without the email tooltip.

## Inherited native evidence

Earlier user-observed acceptance of the unchanged implementation includes fresh opening centring, close/reopen size and position retention, fresh-session Dashboard selection, theme/layout review, wizard scrollbar clearance in both themes, required-field messages, the administrator confirmation surface, temporary-worker readiness, successful staging and separately scrollable populated wizard/main logs.

Production issuance/deployment, scheduler/renewal checks and backup/recovery/removal workflows were exercised in earlier development testing. These are inherited observations, not claims of a new end-to-end production run of this release installer.

## Native release smoke test — 1.0.0-1

The exact release installer was installed on the DSM lab using **Package Center → Manual Install** over the accepted idle development installation without uninstalling.

Observed result:

- Upgrade completed successfully.
- SadlerACME opened normally and displayed **v1.0.0-1**.
- Existing certificate configuration remained present.
- DSM deployment showed **Verified — certificate matches**.
- The SadlerACME certificate remained the DSM default.
- Automatic renewal remained **Enabled — every 6 hours**.
- Scheduler remained **Installed and enabled**.
- Queue watcher and renewal timer remained active.
- The Cloudflare token remained configured.
- QuickStart, Workflow and Recovery opened from **Help & About** with the correct **1.0.0-1** banner.

No staging, production issuance, forced renewal, backup/restore or uninstall cycle was repeated because those functional components are unchanged from the accepted implementation.

**Result: PASS.**

## Not repeated on this exact installer

The release smoke test did not repeat DNS requests, staging/production issuance, naturally due renewal, recovery import or destructive removal. Those functions are covered by earlier development evidence of the unchanged implementation.

Additional NAS models, DSM updates and emergency scheduler-API paths are not universally certified. The package declares x86_64 and DSM 7.0-40000 as its installation minimum; those declarations do not establish a tested hardware/DSM support matrix.

## Publication status

The final native publication gate has passed. The exact SPK tested in DSM is:

`SadlerACME-1.0.0-1.spk`

SHA-256:

`4220114fe2ed523ac7cd222abdc2ecdd0822fb045fb66878f2c37c3232f34d12`

The release may be published as **SadlerACME 1.0.0-1 — Public Beta 1**, marked as a GitHub **pre-release**.

No further certificate issuance is required solely for publication unless a functional component changes.
