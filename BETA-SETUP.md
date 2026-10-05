# SadlerACME public-beta setup

**Public beta. Original project by Shane Sadler.** This guide is for deliberate evaluation on a backed-up or recoverable installation. A beta is not certification of every DSM release or NAS model.

Read [QUICKSTART.md](QUICKSTART.md) for short steps and [WORKFLOW.md](WORKFLOW.md) for the full behaviour. Use [RELEASE-GUIDE.md](RELEASE-GUIDE.md) for upgrades and [RECOVERY.md](RECOVERY.md) for removal. Older retained-data uninstall instructions do not apply.

## Record the starting point

Record NAS model/architecture, full DSM version/build/Update suffix, browser, connection route and package checksum in [BETA-REPORT-TEMPLATE.md](BETA-REPORT-TEMPLATE.md). State whether this is a first installation, an upgrade or a reinstall restoring a recovery backup. Target: x86-64 DSM 7; declared minimum 7.0-40000 is not a verified support matrix. Cloudflare DNS hosting and a DSM administrator account are required.

Use your own domain and a zone-scoped Cloudflare API token with Zone / DNS / Edit and Zone / Zone / Read. Do not use a Global API Key or enter sample domains as production configuration.

## New setup using the wizard

1. Install the exact test SPK and open from the administrator's DSM desktop over HTTPS. Record prerequisite/session failures without bypassing checks.
2. Open Certificate settings → Setup Wizard. Choose a new configuration, enter/review settings and advance with Next. Verify that navigating or going back does not save the draft.
3. Choose Check / Start Worker. Record whether existing automation was reused or the disabled temporary task was created/run, and whether fresh password confirmation was requested.
4. Run Staging Test. Wait for its result and inspect Logs. Staging must not save the draft as production settings or change DSM's certificate/default assignments. TXT cleanup should be recorded only when this run created challenge values; cached ACME authorisations can skip DNS changes.
5. For staging-only testing, stop here using Exit Setup, completing temporary cleanup if prompted. Do not Apply & Save or enable production renewal.
6. Only if deliberate production testing is intended and existing certificates/assignments are backed up: Apply & Save, verify the DSM destination and served certificate, then Finish Setup and choose renewal.

A successful manual fallback does not prove the guided API operation. Unknown event-task schemas, conflicting tasks or duplicates should stop the guided operation. Record the first error before making a deliberate manual correction.

## Normal sections instead

The wizard is optional. Save the desired settings directly, leave renewal off in Automation, create/update the existing permanent bootstrap through Automation, verify the worker, then run Staging Test beside the certificate settings. Production Issue / Apply is a separate deliberate action. **Check Now can renew/deploy an active profile; it is not a read-only diagnostic.** Renew Early forces issuance and is not needed for normal setup testing.

## Upgrade and recovery

Do not uninstall a working installation merely to join testing. Upgrade through Package Center while idle, reuse its task and refresh the DSM desktop. See RELEASE-GUIDE.md for earlier-task migration.

A downloaded recovery file contains private keys but no Cloudflare token or DSM password. Restore through the wizard requires the token again, leaves renewal off and does not issue/deploy. Verify before re-enabling renewal. Expired/missing recovered certificates require an explicit production action.

Uninstall testing belongs on a disposable or recoverable installation. Use Backup & Restore to download a backup, then Uninstall to prepare. Preparation stops background helpers and removes recognised DSM Task Scheduler tasks while retaining application data until Package Center removal. Actual uninstall deletes app data, retaining DSM-installed certificates. Manual recovery guidance is in Uninstall. Wait for independent cleanup of the protected store and persistent data/configuration to finish before reinstalling. For an already-removed older build, use the current assembled helper's `--check` first and review its metadata report before authorising cleanup. The exact SSH fallback and explicit overrides are in RECOVERY.md.

Report each completed/skipped check separately using TESTER-CHECKLIST.md. Never send private keys, recovery exports, API tokens, passwords, session URLs/cookies or raw credential-bearing configuration.
