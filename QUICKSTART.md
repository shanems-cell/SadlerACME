# SadlerACME QuickStart

**Let's Encrypt wildcard and multi-domain certificates for Synology DSM using Cloudflare DNS.**

SadlerACME is designed for Synology users who manage their DNS through **Cloudflare** and want more certificate flexibility than the standard DSM certificate workflow provides.

## Why SadlerACME?

With SadlerACME you can:

- issue **wildcard certificates**, such as `*.example.com`;
- place **multiple domain names / SANs** on one certificate;
- use **Cloudflare DNS-01 validation**, so ACME validation does not depend on exposing a web server on port 80;
- automatically renew the certificate and deploy the renewed certificate back into DSM; and
- manage the process from a DSM application instead of maintaining ACME shell scripts manually.

**Cloudflare DNS is required.** SadlerACME is deliberately focused on Cloudflare rather than attempting to support every DNS provider.

### How SadlerACME fits into DSM

SadlerACME provides a Cloudflare DNS-01 workflow inside DSM for wildcard and multi-domain certificates. It keeps certificate validation, automatic renewal and deployment together in a guided application. The finished certificate is installed into DSM, where it can be assigned to DSM itself and supported services such as reverse proxies, web applications and mail services.

The key distinction is the **Cloudflare DNS-01 workflow**, not a claim that every certificate capability listed above is exclusive to SadlerACME.

## Public beta

SadlerACME is currently released as a **public beta**. It has undergone extensive development and lab testing, including certificate issuance and deployment, scheduled renewal, recovery and removal workflows, and native DSM interface testing.

It has not yet been tested on every supported Synology model or DSM 7 point release. Beta users should maintain normal NAS backups and retain an alternative way to access DSM while evaluating the package.

If you encounter a problem, report the **Synology model, DSM version, SadlerACME version, what you were doing, and the relevant SadlerACME log output**. Do not include Cloudflare API tokens, DSM passwords, private keys, recovery backups or other credentials in reports.

## Supported platforms

SadlerACME is currently provided for **Synology NAS systems running DSM 7.0 or later on x86_64 (Intel/AMD) processors**.

The current package is not built for ARM-based Synology models. Testing has been performed on x86_64 DSM 7 systems. Other compatible x86_64 Synology models are welcome in the beta, but may not yet have been individually verified.

XPEnology/Arc environments are useful development and test environments but are not presented as officially supported Synology platforms.

## Quick setup

**Updating an existing installation:** use Package Center → Manual Install while SadlerACME is idle, then close SadlerACME, refresh the DSM desktop and reopen it. Unless the release notes for a particular update say otherwise, an ordinary upgrade does not require uninstalling the package, restoring a backup or issuing a new certificate.

**After an earlier uninstall:** run the current standalone helper's read-only check first if old SadlerACME data may remain. Use the current helper for DSM configuration-alias support. See [Recovery](RECOVERY.md); do not reinstall over pending cleanup.

1. **Install** the current SadlerACME `.spk` package through Package Center → Manual Install.
2. **Open** SadlerACME from an administrator's DSM desktop over HTTPS. After upgrading, refresh DSM and reopen the app.
3. **Dashboard → Setup Wizard** (also available in the Certificate settings heading). Choose a new configuration or select a downloaded SadlerACME recovery backup in the wizard’s first step. Backup & Restore → Start Restore Wizard opens that same step. The wizard is optional and never starts automatically.
4. **Review settings and enter your Cloudflare token.** Use your own domains, for example `example.com` and `*.example.com`, and a unique DSM certificate description. The token needs Zone / DNS / Edit and Zone / Zone / Read for the required zones. Backups do not include it.
5. **Check / Start Worker.** Existing automation is reused; fresh setup starts temporary processing. Confirm your DSM password when requested.
6. **New setup:** Run Staging Test, then explicitly choose Apply & Save. **Restore:** confirm Restore Backup; it does not issue or deploy. Verify the recovered certificate and use Re-deploy Existing only if needed. An absent or expired certificate requires Issue / Apply.
7. **Finish setup.** Install/verify the permanent bootstrap task, remove temporary setup and choose automatic renewal. DSM may request fresh password confirmation.
8. **Verify** Dashboard health, DSM certificate assignments and the certificate actually served by your services. Download a recovery backup from Backup & Restore and keep it secure.

**If temporary processing stops:** keep the wizard open and choose **Restart Worker** when offered. Confirm DSM approval if requested, wait for readiness, then retry the intended action yourself. The draft stays open; restart does not automatically repeat a restore or certificate action. The message may identify the one-hour expiry as a possible cause when the wizard previously observed temporary processing; it does not confirm the stop cause.

Use the horizontal top navigation to move between **Dashboard, Certificate settings, Automation, Backup & Restore, Uninstall, Logs, and Help & About**. On narrow windows, use the compact three-line button at the top right; choosing a page closes the compact menu. Dark mode retains the familiar grey icons and muted blue accents. Use the header’s **Light mode / Dark mode** button to switch instantly. The preference is kept in this browser, not in certificate settings. If browser storage is unavailable, the selection lasts only for the open page.

**First opening:** Dashboard is the default when there is no remembered tab in the current browser session. The wizard remains optional. The application is designed to open centred on a fresh launch and to retain subsequently moved/resized window geometry through DSM.

**Dashboard status:** refresh the app to read current metadata if a page has been left open. Check the last-verification and worker timestamps; a past cached next-check time is not a future deadline. A refresh does not itself prove a new certificate was issued.

**Normal sections still work:** Save Settings saves immediately; testing and Issue / Apply are separate actions. Automatic renewal is controlled in Automation. Check Now can renew/deploy; Renew Early forces renewal.

**To remove:** download a backup from **Backup & Restore** if wanted → open **Uninstall** → Prepare for Uninstall → wait for Ready → uninstall in Package Center. Preparation stops background helpers and removes recognised DSM Task Scheduler tasks; settings and recovery data remain until Package Center removal. Manual recovery guidance is in Uninstall. Wait for cleanup of the protected store and persistent package data/configuration; DSM-installed certificates remain. Read [RECOVERY.md](RECOVERY.md) if preparation fails. See [WORKFLOW.md](WORKFLOW.md) for the full workflow. Never include tokens, passwords, recovery backups or private keys in reports.

**Orderly wizard exit:** after this wizard starts or reuses a temporary Setup task, Exit Setup requests task removal through DSM and stops temporary processing where still active. Complete any administrator approval and wait for the result. If cleanup is cancelled or fails, the wizard stays open and reports the problem. Permanent automation is not stopped by exiting a wizard which only reused Bootstrap.

**Logs:** the viewer fills the available height below its controls. Scroll inside the viewer for long logs. Very short or zoomed views can still scroll the page to keep controls reachable. This does not change saved log content.
