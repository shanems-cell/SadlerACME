# SadlerACME 1.0.0-1 — release validation

**Public Beta 1 candidate. Local release checks completed; native installation/open/installed-help smoke check and publication approval remain pending.**

Original project by Shane Sadler. Prepared 5 October 2026.

## Release boundary

This is a documentation and metadata promotion of the accepted development implementation. Earlier native results remain earlier results; they have not been renamed as newly executed tests of this exact installer. Historical reports remain with the original development materials, outside this public release bundle.

The accepted baseline installer is identified by SHA-256 rather than an obsolete release label:

`26e6cc18e79279d9b000333dddac49f6999d2104c602d685ca2e90c54c6cbd50`

The final release installer is identified by:

`4220114fe2ed523ac7cd222abdc2ecdd0822fb045fb66878f2c37c3232f34d12`

## Exact package comparison

The payload file set and file modes remain unchanged. Exactly four payload files differ from the accepted installer: the three generated guides (`ui/QUICKSTART.html`, `ui/WORKFLOW.html`, `ui/RECOVERY.html`) and `ui/index.cgi`.

The CGI difference is limited to the version display and one legacy-task explanatory sentence that no longer names an obsolete release. After normalising those two strings, the assembled CGI is byte-identical. INFO changes are limited to version, the Cloudflare/wildcard/multi-domain description, and `beta="yes"`.

The launcher, both stylesheets, workflow/theme JavaScript, scheduler/authentication bridge, privileged certificate worker, emergency helper, all ten systemd units, lifecycle scripts, privileges, icons, licences and pinned vendor implementation are unchanged. No certificate issuance, renewal, recovery or uninstall logic was modified.

Protected hashes:

- Certificate worker: `3c1fb6d1edbcd1cfec4701684e398255bea3c2d753d9f8096fa2e0f1a1c5c927`
- Emergency helper: `fff8b068aaf5d9b8242b5d20c93ab7a7bfc53ec3e7063634ac649e134c3dc4b5`

`tests/RESULTS-1.0.0-1-package.json` records the allowed changes, complete payload hashes, modes, ownership and protected-file identity. Verification also checks safe archive paths, no unexpected file/link types, and agreement between the assembled source and installer.

## Local checks actually run

| Check | Result |
| --- | --- |
| Python regression/workflow/scheduler/status suites | 214 unittest cases passed across 10 suites |
| Window sizing | 17/17 fixtures passed |
| Window placement: self-contained model | 38/38 scenarios passed |
| Same placement scenarios with selected supplied DSM definitions | 38/38 passed; DOM/base rendering remains simulated |
| Theme UI | 13/13 fixtures passed |
| Temporary-worker UI | 20/20 fixtures passed |
| Workflow UI | Existing full suite passed; no invented numeric case count |
| Rendered CGI/UI browser checks | 258/258 passed |
| Wizard scrollbar clearance/hit targets | 84/84 passed |
| Selected enabled-text contrast pairs | 44/44 passed; not a full accessibility audit |
| Syntax, configuration and image assets | Passed; detailed count in the syntax transcript |
| Installed-help rendering | Six wide/narrow guide-layout cases passed |
| Public documentation and installed-help integrity | Passed after completing the validation document; detailed checks in the documentation report |
| Illustrated guide | Eleven rendered pages visually reviewed; original selected screenshots retained |
| Source rebuild and release-archive checksums | Recorded in the release-bundle verification report |

The two placement runs exercise the same 38 scenarios in different harnesses, not 76 independent native tests. Test-count types are not combined into one certification number. Tests use temporary filesystems, synthetic configuration and mocked or intercepted DSM/ACME boundaries. The rendered UI and guide tests block external requests. No real secrets or certificate operations are required for them.

Current transcripts use `tests/RESULTS-1.0.0-1-*`. An early documentation-check invocation stopped because VALIDATION.md had not yet been written; it is retained as an initial assembly check, not counted as a pass. The final invocation follows completion of all referenced documents.

## Documentation and screenshot treatment

README and QuickStart remain release-version-independent. All current written public documents and installed guides use generic wording or **1.0.0-1**, without obsolete SadlerACME release references. Old helper filenames and obsolete workaround notes are removed; current recovery commands, warnings and guard conditions remain.

The installed guides are regenerated from their Markdown source. Their banners identify **SadlerACME 1.0.0-1 — Public Beta**. Local guide and recovery-helper links are checked against the installed payload. Upstream engine versions, DSM prerequisites and licence identifiers are deliberately preserved.

Original documentation screenshots retain their captured version labels, as approved. They illustrate the unchanged interface and are not presented as new native acceptance of this release. All eleven selected screenshots match their original bytes. Help & About uses the replacement image without the email tooltip. The Word guide contains the same selected images and explains their captured-version status.

The public overview highlights Cloudflare DNS-01, wildcard and multi-domain support without publishing an unsupported claim that every capability is absent from DSM's built-in workflow.

## Inherited native evidence

Earlier user-observed acceptance of the unchanged implementation includes fresh opening centring, close/reopen size and position retention, fresh-session Dashboard selection, theme/layout review, wizard scrollbar clearance in both themes, required-field messages, the administrator confirmation surface, temporary-worker readiness, successful staging and separately scrollable populated wizard/main logs.

Production issuance/deployment, scheduler/renewal checks and backup/recovery/removal workflows were exercised in earlier development testing. These are inherited observations, not claims of a new end-to-end production run of this release installer. Non-due renewal checks do not by themselves establish naturally due unattended renewal. Extreme browser zoom has not been certified as universally accessible.

The optional placement harness reads selected static functions from privately supplied DSM diagnostics. It simulates unreported base rendering and settings storage; it is not a live DSM run. The proprietary diagnostic files are not included in the public source.

## Not performed on this exact installer

No native DSM installation or upgrade, live DSM service restart, DNS request, staging/production issuance, naturally due renewal, recovery import or destructive removal was executed in this release-build environment. Additional NAS models, DSM updates and emergency scheduler-API paths are not universally certified.

The package declares x86_64 and DSM 7.0-40000 as its installation minimum. Those declarations do not establish a tested hardware/DSM support matrix.

## Final publication gate

Update the existing idle lab through Package Center Manual Install without uninstalling. Refresh DSM, reopen SadlerACME, confirm **1.0.0-1**, and open QuickStart, Workflow and Recovery from Help & About. Confirm the Cloudflare-focused package description and the helper download link. This is a small installation/open/help check, not a request to repeat certificate or destructive recovery operations.

Numeric package-version syntax and beta metadata were checked against Synology's [required INFO fields](https://help.synology.com/developer-guide/synology_package/INFO_necessary_fields.html) and [optional INFO fields](https://help.synology.com/developer-guide/synology_package/INFO_optional_fields.html). The documentation recommends increasing the build number; acceptance of the first-public-release version transition must therefore be confirmed on DSM, not inferred solely from the major-version change. If it is refused, retain the installed package and report the message rather than uninstalling to bypass it.

Publish only after this check and explicit release approval. No repository has been modified and no public release has been created by this local preparation.
