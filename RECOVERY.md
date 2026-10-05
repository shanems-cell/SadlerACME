# Backup, restore and removal

**Public beta. Original project by Shane Sadler.** Use these instructions for the current release. Recovery backups contain private keys; removal can permanently delete SadlerACME's local settings and recovery data. Release-specific evidence and limitations are recorded separately.

## Download a recovery backup

1. Open **Backup & Restore → Download Backup**.
2. If protected processing is not running, follow the temporary-worker/password prompts.
3. Save the downloaded JSON file somewhere outside the directories being removed. A copy on another device is preferable for NAS recovery.
4. Check that the download completed before treating it as your backup.

The export includes selected settings, the stored certificate/private key/chain when present, its domain/key metadata and the production ACME account key when available. A settings-only backup is supported when no certificate has been issued. It does not include the Cloudflare token, DSM passwords/sessions, raw acme.sh configuration, executable hooks, queued work, application helpers, diagnostic logs or full historical transaction backups.

**The recovery file contains private keys.** It is not an encrypted vault. Store it securely and never attach it to a public issue or diagnostic report. Cloudflare credentials are deliberately excluded rather than encrypted into the backup.

Download is the only offered backup destination. The app may stage a protected file while generating/transferring it; the authenticated download removes that temporary file after transfer, and unused downloads expire after 15 minutes with timer-driven cleanup. A failed or interrupted download is not evidence that a usable copy was saved. Retry and save a complete file; expired download links need a new export.

The ordinary operational copy of the Cloudflare token remains protected on the NAS while the app is in use, because unattended DNS renewal needs it. Backup exclusion does not disable that operational storage.


## Preview a downloaded backup

Choose **Backup & Restore → Start Restore Wizard** to open the wizard at **Choose setup**. Select the recovery JSON file there; this is the only recovery-file picker. Its preview shows the selected file’s details before continuing. Selecting a file does not import it, change settings or contact the certificate authority. Full certificate/key validation still takes place during the explicit restore operation. **View Logs** opens the existing Logs tab.

## Restore after reinstall

1. Install the package, open it from the DSM administrator desktop and choose **Setup Wizard → Restore a downloaded SadlerACME backup**. Alternatively use **Backup & Restore → Start Restore Wizard** to open the same wizard, then select the file in its first step.
2. Review the imported settings and enter the Cloudflare token again. DSM asks for fresh password approval when a task operation requires it.
3. Start/check protected processing and explicitly confirm **Restore Backup**.
4. Wait for the restore result. It replaces SadlerACME's recovery state and saved settings, leaves automatic renewal disabled and does **not** request a certificate or change DSM's installed certificate.
5. Verify the certificate and DSM match. If the valid restored certificate needs deployment, explicitly choose **Re-deploy Existing**. A settings-only backup, expired certificate or otherwise unusable profile needs **Issue / Apply** before renewal can be enabled.
6. Finish permanent automation, verify service certificate assignments and enable renewal only after the recovered installation is ready.

Restore validates the document format/size, allowed fields, settings, PEM material, matching private key, domain set and key type. It reconstructs the ACME profile from selected data rather than executing restored shell configuration. A successful restore, including a settings-only backup, transactionally records that the restored state supersedes legacy migration. Later certificate actions cannot revive the older certificate from that legacy location; rollback preserves the previous migration marker. The old files are not automatically deleted by restoration. Encrypted private-key blobs are not imported. An expired certificate can be recovered as data, but it is not accepted for deployment as a valid replacement.

The backup's settings are shown for review during restoration; change domains or other non-secret options through Certificate settings after restoring. Restore is an explicit committed change, so exiting afterwards does not undo it. An interrupted restore uses protected transaction data to recover the earlier local state; do not delete that data to silence an error.

If an earlier wizard Apply has an unresolved reconciliation record, restore is blocked. Resolve the application through the reported Apply & Save or Issue / Apply path first; automatic renewal remains paused while the certificate/configuration outcome is uncertain. Do not erase the journal or import a backup over it to hide an incomplete deployment.

A saved ID from another installation is not blindly imported. SadlerACME checks this NAS's DSM inventory and uses an exact unique description match when appropriate. If no description matches, it can recognise a unique existing entry by the recovered certificate's SHA-256 fingerprint. Duplicate descriptions or fingerprint matches are blocked; choose a unique existing DSM description before applying. Unreadable inventory entries prevent proving a unique match and must be resolved. Restoration itself does not reassign DSM services.

If temporary processing has stopped, keep the wizard open and choose **Restart Worker** when offered. DSM may request fresh administrator approval. Wait for readiness and explicitly retry **Restore Backup**; restart preserves the draft and does not replay the restore. When the wizard previously observed temporary readiness, it mentions the one-hour limit as a possible cause; otherwise it gives general worker-unavailable guidance. It does not establish the exact stop cause. Reopening the wizard alone is not a worker-start action and discards its uncommitted draft.

If restore rejects a file, keep the original backup, read the error and correct the cause. Do not hand-edit private keys or add raw acme.sh files to the JSON. A certificate exported from DSM is not a SadlerACME recovery backup.

## Legacy-source validation errors

If a certificate operation reports “Legacy certificate source cannot be verified safely”, do not alter permissions to make that data appear trusted. Package-writable paths are not trusted root-owned certificate sources. Keep the originals for administrator review and follow the reported error. Explicit restoration uses the validated recovery-backup workflow rather than executing legacy shell configuration.

## Normal uninstall

1. Download a recovery backup if wanted and confirm that it has been saved.
2. Open **Uninstall** and choose **I have saved a recovery backup**, or explicitly choose to continue without one.
3. Choose **Prepare for Uninstall**. Confirm DSM password requests for task removal when needed.
4. Wait for **Ready to uninstall**. If preparation fails, stop and follow its error; do not assume task deletion alone completed preparation.
5. Uninstall **SadlerACME** in Package Center.

Preparation removes the recognised SadlerACME Bootstrap/Setup tasks from DSM Task Scheduler, stops background helpers and triggers, waits for current protected work through the shared lock, cancels queued requests and arms an independent cleanup service. It **does not erase settings or production certificate recovery data**. Temporary downloadable exports are removed during preparation; save the downloaded backup beforehand.

Package Center's uninstall check requires a protected readiness value and an active armed cleanup monitor. A writable or stale flag alone is insufficient. Preparation also records the resolved physical package data/configuration paths and each directory's device/inode identity in protected records. The post-uninstall hook signals removal; the privileged monitor waits until DSM has removed the package directory, verifies all recorded storage targets, then removes those persistent directories, SadlerACME's protected store and its own helper. If the fixed DSM alias exists, uninstall also requires its current protected identity record. Preparation performed with an older build must be repeated after upgrading; the older monitor is not accepted as complete alias cleanup. If Package Center refuses removal, application data remains. Restarting normal processing cancels prepared readiness.

Cleanup runs independently after Package Center removes the package. **Wait for protected, persistent package data/configuration and helper cleanup to finish before reinstalling.** The installer refuses a new installation while a prior removal remains armed, preventing an old cleanup process from deleting newly restored data. If cleanup stays pending, use the SSH read-only check and resolve its reported failure.

An untouched fresh installation with no attempted automation, protected root state, legacy `var/root` data or pending removal state can uninstall directly. In that route the package account clears its own data/configuration contents; empty DSM-managed storage directories and DSM's configuration alias may remain. That path does not start a root cleanup helper to remove the alias. Once automation setup has been attempted, even if it failed partway, preparation or explicit administrator recovery is required. Simply turning automatic renewal off is not preparation.

Confirmed prepared removal deletes SadlerACME settings, stored Cloudflare credentials, local certificate/private-key copies, ACME state, pending work and recovery/history data from the validated package data/configuration and protected locations. It does **not** delete or revoke DSM-installed certificates or alter their assignments. Existing services can continue using DSM's copy until it needs replacement, but SadlerACME is no longer renewing it. Arrange replacement before expiry.

### Why package data needs explicit cleanup

Synology documents package `var` and `etc` as persistent locations that survive uninstall: see [DSM package filesystem layout](https://help.synology.com/developer-guide/integrate_dsm/fhs.html). Removing `/var/packages/sadleracme` registration or `/usr/local/etc/sadleracme` protected state therefore does not prove that these other directories were deleted.

The package data location can contain certificate/key copies, ACME state, backups, status and logs. Configuration can contain operational credentials. Normal prepared removal therefore validates and cleans both locations; removing only the package registration is not sufficient.

Cleanup accepts only these fixed SadlerACME path families, not arbitrary caller-supplied directories:

| Kind | DSM storage candidates |
| --- | --- |
| Package data (`var`) | `/volumeN/@appdata/sadleracme`, `/usr/local/packages/@appdata/sadleracme` |
| Package configuration (`etc`) | `/volumeN/@appconf/sadleracme`, `/usr/syno/etc/packages/sadleracme` |

Here `N` is a numeric volume number. Normal preparation records the actual registered targets, rather than deleting every candidate. The validated identity must still match after Package Center removal. A replaced directory, unsafe parent, symlink at the physical target, or mount at/below the target stops deletion. The one fixed DSM configuration alias described below is handled separately; this is not permission to follow arbitrary symlinks. Missing targets are compatible with cleanup already having completed; a different directory at the same name is not. Resolve the reported condition instead of bypassing these checks.

DSM can represent `/usr/syno/etc/packages/sadleracme` as a root-owned symlink pointing directly to the physical `/volumeN/@appconf/sadleracme` directory. The helper recognises only this fixed alias after validating its root ownership, parents and direct target. It records the link identity separately from the physical directory and refuses a changed, chained or unsafe link. Cleanup unlinks the verified alias only after the physical configuration target is removed. It does not weaken validation of the target itself.

A displayed symlink mode of 777 is not by itself a reason to change permissions. Its verified owner, protected parent, exact target and recorded identity are the relevant checks. Do not modify or remove the DSM link manually just to silence the helper's report.


A clean reinstall without a backup normally requires fresh certificate issuance. Repeated fresh issuance can encounter Let's Encrypt limits. With a valid recovery backup, restoring local management does not itself require another certificate.

## Emergency SSH removal

Open the manual recovery guidance from **Uninstall**; the reference help is also available in **Help & About**.

This route is for an administrator when the web UI, worker, readiness writer or normal package hooks no longer work. It does not rely on those normal components. It still needs functional DSM package management, systemd and a writable filesystem; it cannot safely remove another application's tasks or repair corrupt DSM registration.

Use the assembled standalone **sadleracme-emergency-remove-1.0.0-1** supplied with this release. The installed filename remains `sadleracme-emergency-remove`. Keep the standalone copy outside the package, verify its supplied checksum and do not run the unassembled `src/bin` template from the source archive.

If the current installed copy is readable, save it to the signed-in user's home directory without running it:

```sh
cp /var/packages/sadleracme/target/bin/sadleracme-emergency-remove \
  "$HOME/sadleracme-emergency-remove-1.0.0-1"
```

If the package is already gone, transfer the delivered standalone file to that location. The installed recovery-help page also offers **Download SSH recovery script**. Use the delivered assembled helper or the verified installed copy and review its supplied checksum.

First perform a read-only check:

```sh
sudo sh "$HOME/sadleracme-emergency-remove-1.0.0-1" --check
```

The check lists fixed SadlerACME storage candidates and metadata, including package configuration and its recognised DSM alias, even if the package is absent. It does not read certificate keys, configuration values or log contents. It also inspects tasks and service/recovery state. An early failure is not proof of complete cleanup. Review the report before any removal. A read-only check does not authorise removal; review the result before choosing any destructive operation.

To remove only recognised SadlerACME tasks and then the package/data through SSH, explicitly authorise both actions:

```sh
sudo sh "$HOME/sadleracme-emergency-remove-1.0.0-1" \
  --remove --remove-tasks --confirm 'REMOVE SADLERACME DATA'
```

**The root EventScheduler deletion API used by `--remove-tasks` has not been independently certified on every DSM build.** Prefer the normal guided removal route when it is available; retain this emergency-path limitation when evaluating the beta. The tool inspects fixed SadlerACME task identity/configuration before deletion and verifies absence afterwards. Unknown, conflicting or unremovable tasks stop cleanup; it does not edit the scheduler database. If DSM Task Scheduler is available, you can instead remove the listed tasks there and run:

```sh
sudo sh "$HOME/sadleracme-emergency-remove-1.0.0-1" \
  --remove --confirm 'REMOVE SADLERACME DATA'
```

After tasks are absent, the script stops SadlerACME triggers and services, checks that protected work has stopped, temporarily replaces only this package's failing stop/uninstall hooks, asks DSM's package manager to uninstall it, and deletes app-owned protected and validated persistent package data/configuration only after package removal is confirmed. When the package is already absent, it can inspect and remove the fixed residual candidates after the same explicit confirmation. It records directory identities durably before deletion so a retry cannot silently adopt a replacement directory. It also removes only the known remaining package unit files that are regular root-owned files; unexpected paths or symlinks are retained and reported as incomplete cleanup. If package removal fails, the normal hooks are restored where the package still exists and application data is retained. DSM-installed certificate storage is outside its deletion scope.

### Explicit overrides

The normal emergency command still refuses unsafe or unknown conditions. These options have different meanings and should not be added as a blanket force switch:

| Option | Meaning |
|---|---|
| `--remove-tasks` | Authorise removal of verified fixed SadlerACME scheduler tasks through DSM's API; reject conflicts and verify absence afterwards |
| `--tasks-removed` | When scheduler inspection is unavailable, attest that an administrator has independently checked and removed the tasks; it is not permission to ignore tasks that were found |
| `--stop-active-work` | Permit interruption of a stuck SadlerACME worker; ordinarily wait for a real certificate operation to finish |
| `--discard-recovery-data` | Permit deletion of an interrupted certificate transaction's recovery files, after checking DSM's active certificate and accepting loss of recovery material |

Interruption can leave certificate-deployment recovery work. The tool rechecks after stopping and can still require the separate recovery-data decision. Keep backups and inspect DSM before taking that step.

When it reports failure, use its specific diagnostic. Do not retry by recursively deleting `/var/packages`, certificate archives or DSM registration databases. A filesystem/service-control failure must be repaired before cleanup can be verified.

### Verify removal

Rerun the read-only check:

```sh
sudo sh "$HOME/sadleracme-emergency-remove-1.0.0-1" --check
```

Confirm that Package Center no longer lists SadlerACME, its scheduler tasks are absent and its protected data is gone. The current helper also reports fixed persistent data/configuration candidates. Confirm that none contain residual data and no armed cleanup remains; empty DSM storage directories and the DSM configuration alias can be expected after the untouched-install path. Paths moved manually outside the documented scope are not searched or deleted. Check that the services you use still present the intended DSM-installed certificate. The standalone script and any recovery file saved in your own directory are intentionally not self-deleted; remove or retain those copies deliberately.

## If preparation succeeds but removal is postponed

The application data remains, but automation has been stopped. To resume operation, start the existing setup/automation workflow, recreate the permanent task if necessary and verify renewal status. Resumption invalidates the old readiness state; prepare again before a later uninstall.

If a browser closes during temporary setup, wait for active work to finish and use the app's cleanup/recovery route. The one-hour worker lease does not guarantee that DSM has deleted the disabled temporary scheduler task. Do not call the installation untouched merely because no production certificate was issued.
