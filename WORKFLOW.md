# Setup and daily workflow

**Public beta. Original project by Shane Sadler.** This guide describes the setup, certificate, automation and recovery workflows. Release-specific test evidence and limitations are recorded separately in the release documentation.

## Optional Setup Wizard

Open **Dashboard → Setup Wizard** or **Certificate settings → Setup Wizard** when you want guidance. It does not run automatically on installation or upgrade. It always has the same name and starts from the latest saved settings, including settings saved directly outside the wizard.

| Step | New or changed configuration | Restore a recovery backup |
|---|---|---|
| Choose setup | Set up or update the current configuration | Select a SadlerACME JSON recovery backup |
| Certificate settings | Review description first, then domains, key type, account email, token and options | Review the backup's settings; enter the Cloudflare token again |
| Start background processing | Reuse existing automation or start a temporary worker | Same worker startup, needed for protected restoration |
| Test/apply or restore | Run Staging Test, then Apply & Save | Explicitly restore; verify DSM and re-deploy only if needed |
| Finish setup | Verify/install permanent startup, clean temporary setup and choose renewal | Same, with renewal disabled until restored certificate checks permit it |

**Next** and **Back** keep edits in memory. They do not save production settings. **Run Staging Test** tests the draft using the staging service, without changing saved production settings or DSM's installed certificate. Changing the draft after testing requires another staging test before wizard application.

**Apply & Save** asks for confirmation, applies the proposed production configuration and saves after successful application. It leaves automatic renewal off until the final step. If the certificate application succeeds but writing settings fails, the app reports that distinction: keep the wizard open and follow its retry guidance rather than assuming DSM was unchanged.

If Apply fails or is interrupted, a protected reconciliation record tracks the previous state and the proposed change. Recovery compares DSM's current certificate material as well as metadata before deciding that it is safe to restore the prior local state. If DSM may already have changed, **automatic renewal stays paused and backup restoration is blocked** until the application is reconciled. Follow the error to retry Apply & Save with the intended configuration, or use normal Issue / Apply to reconcile the saved settings. Do not delete the recovery record to bypass that guard. A valid certificate issued before a later failure is retained for a safe retry when applicable.

The application checks that saved settings have not changed in another window before committing. If they have, reopen the wizard to load the current version instead of overwriting someone else's changes.

**Exit Setup** asks before discarding an unfinished draft. It does not undo settings already committed through Apply & Save, Restore Backup or the normal Settings form. Going back during the open wizard retains entered values; reopening starts from saved settings. A restored backup's non-secret settings are reviewed without editing during import; edit them normally after restoring if required.

## Worker startup and passwords

An existing valid bootstrap task and healthy worker are reused. New guided setup creates **SadlerACME Setup**, a disabled Boot-up task with one fixed command:

```sh
/bin/systemctl start pkg-sadleracme-setup.service
```

The wizard requests an immediate run of that disabled task. Temporary processing pauses the renewal timer and has a one-hour lease. Active certificate work holds the shared worker lock and is allowed to finish before lease cleanup.

When a status/recheck reports processing unavailable while the wizard remains open, it clears the old ready state and its worker-readiness success banner and offers **Restart Worker**. Other operation outcomes are not erased. An idle browser view may be stale until status is checked. When the wizard previously observed temporary readiness, the message explains that the worker may have reached its one-hour limit. Otherwise it describes worker unavailability without assuming a lease expiry. The message does not establish the stop cause. Restart uses the same DSM approval and readiness checks as initial startup, keeps the draft and returns control for an explicit retry. It does not automatically repeat staging, application or restoration. Closing and reopening the wizard alone does not restart the worker and loses uncommitted draft values.

At the final step, the wizard installs/verifies the permanent enabled **SadlerACME Bootstrap** Boot-up task:

```sh
/bin/systemctl start pkg-sadleracme-bootstrap.service
```

It then removes the temporary task and completes permanent automation. The task starts background services; it is not a separate schedule for each domain or certificate.

DSM administrator confirmation goes directly to DSM. SadlerACME does not store the password or keep an approval token across the wizard. Another confirmation may be needed for a later task change or cleanup. This is expected and does not discard wizard progress.

Use Exit Setup to perform orderly temporary cleanup. Once this wizard has explicitly started a recognised temporary Setup task, cleanup applies whether the task was newly created or reused. Task deletion still requires DSM approval when requested; failed or cancelled cleanup keeps the wizard open and reports that removal was not confirmed. Merely opening a wizard does not claim ownership of another temporary task. If the browser closes unexpectedly, the worker lease limits temporary processing, but a disabled SadlerACME Setup task may remain and need removal. Existing permanent automation is not treated as wizard-owned temporary state. Follow [RECOVERY.md](RECOVERY.md) for failed cleanup.

Guided task discovery requires a recognised complete DSM task inventory. Duplicate names, unknown response schemas or conflicting task configuration stop the operation for review. Existing manual Create/Update controls remain available for supported task recovery; do not create duplicate tasks to bypass a diagnostic.

## App sections

The dark DSM-style navigation uses grey icons and muted blue accents. At normal widths the seven sections appear in a horizontal bar beneath the header. At 820 px and below, a compact three-line button appears at the top right; its menu opens below the header and closes after a page is chosen.

| Section | Purpose |
|---|---|
| Dashboard | Certificate/deployment health, expiry, automation status and Check Now |
| Certificate settings | Saved certificate configuration, optional wizard, staging, Issue / Apply, re-deployment and advanced Renew Early |
| Automation | Bootstrap management, background-service state and automatic renewal |
| Backup & Restore | Download recovery data and open the restore wizard |
| Uninstall | Backup acknowledgement, Prepare for Uninstall, readiness and manual recovery guidance |
| Logs | Diagnostic output |
| Help & About | QuickStart, workflow/recovery help, version, original-project credit and licence |

Use a conventional ASCII account email. The application deliberately rejects quoted/non-ASCII email forms and shell/configuration metacharacters rather than passing them into acme.sh's stored configuration.

**Save Settings** outside the wizard saves immediately. It neither requires staging nor issues/applies a certificate. Saved domain/key changes can therefore differ from the active certificate. The app reports that Issue / Apply is required, and automatic renewal of that changed configuration waits for application. Wizard draft isolation does not change this direct-save behaviour.

Check Now can renew when due and deploy an active profile. Renew Early deliberately requests early renewal and should not be used to test a visual change. Re-deploy Existing uses the stored production certificate rather than asking the CA for another one; deployment still validates that it is suitable.

The current/last-operation panel near the certificate actions links to Logs. It is not a duplicate of raw log-tail output.

## Existing DSM certificate entries

SadlerACME manages one certificate configuration containing one or more domain names. Issuing a replacement certificate does not inherently create another DSM entry.

The saved DSM certificate ID takes priority. If it is unavailable, an exact unique description match can identify the existing entry. No match requires a new entry; multiple matching descriptions stop application. Domains alone do not identify the destination. A backup does not blindly restore another NAS's certificate ID.

Replacing an existing entry preserves its identity and assignments. A newly created entry does not automatically inherit every assignment from an old entry. Verify assignments in DSM and test what each service actually serves.

The destination is checked before production issuance to avoid requesting a certificate when description ambiguity is already known. If the current certificate already matches the applied configuration and passes validation, it can be reused.

The Dashboard’s automatic-renewal label distinguishes the saved preference from checked background-service state. A preference set to on does not by itself establish that renewal is running; inactive or unknown processing is described separately.

A page left open can contain cached verification metadata. Use the app’s refresh control and compare **Last verified**, the worker timestamp and the next-check state. An elapsed cached next-check time must be described as awaiting fresh status rather than presented as a future deadline. Refreshing metadata does not request fresh issuance; **Check Now** remains a separate action that can renew/deploy when due.

Use **Uninstall** when removing the app. Preparation stops background helpers, removes recognised DSM Task Scheduler tasks and handles pending work while retaining saved settings and certificate recovery data. Package Center performs the actual removal; only then does prepared cleanup delete app data. Manual recovery instructions are kept with Uninstall.

## Restore is an explicit change

Select the recovery file only in the wizard’s first step. **Backup & Restore → Start Restore Wizard** opens that step instead of offering a second file picker.

Restore Backup replaces SadlerACME's configuration/recovery state after validation and confirmation. It requires a fresh Cloudflare token, switches renewal off and does not issue or deploy a certificate. Complete details and failure recovery are in [RECOVERY.md](RECOVERY.md).

## Reopening after a failed Apply

Closing a wizard discards its draft and that draft's staging approval. Reopening starts from saved settings, so re-enter the intended configuration and pass staging again before Apply & Save becomes available. A valid retained production candidate is stored separately in protected state and can be reused for a matching explicit application. Do not assume reuse without checking its log, and do not roll back the VM to a pre-issuance snapshot solely to retry import.

## Appearance and space

The shared header switches between the original dark appearance and a DSM-inspired light palette. This is a browser preference (`sadleracme.theme`), not a saved certificate option; the button neither submits the form nor restarts processing. Open forms and wizard drafts are not rebuilt when the palette changes. Theme persistence is scoped to the browser origin: different NAS addresses/ports/browser profiles can have different selections.

The desktop certificate form places its description before account email and uses the domains field beside the shorter options. It stacks naturally in a narrower window. Save settings and certificate actions remain distinct. Setup Wizard no longer occupies a separate introduction card.

The Logs page gives the remaining window height to its viewer. Wizard logs reserve the step heading and footer first; the step content can scroll separately if it is long. On very short windows fallback scrolling keeps the footer reachable. While reading older lines, live updates do not force the viewer to the bottom; scrolling near the bottom resumes following new text.

Staging shows a waiting explanation while its existing job is running. Closing a wizard hides obsolete worker-readiness warnings during confirmed orderly cleanup; real cleanup/approval failures are still reported, and no state is discarded to bypass a failure.
