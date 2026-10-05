# SadlerACME implementation notes

Navigation is Dashboard, Certificate settings, Automation, Backup & Restore, Uninstall, Logs, and Help & About. The existing Settings/About element identifiers remain for compatibility. The navigation is dark and compact, with grey icons and muted blue accents. It is horizontal beneath the header at normal widths; at 820 px and below a compact three-line button at the top right toggles the same seven sections. Backup/restore and uninstall are separate; manual recovery belongs with Uninstall. Preparation stops background helpers and removes recognised DSM Task Scheduler tasks while retaining settings and recovery data until Package Center removal.

Dashboard refresh must identify metadata freshness and must not present an elapsed cached next-check timestamp as an upcoming deadline. The read-only status response adds freshness/deadline fields and filters expired cached next-check timestamps. Record exact current-build validation in VALIDATION.md. The following describes the established workflow and its security boundaries.

## Assembly and workflow

Worker extensions live in src/lib/*.sh, assembled into src/bin/sadleracme-root at its `# @WORKER_EXTENSIONS@` marker by tools/assemble_worker.py before build/test. The resulting worker remains a single hash-verified shell program. No package-writable shell file is sourced by root.

CGI adds JSON POST actions, all behind existing DSM admin session + CSRF checks. JSON body: {action,csrf,config?,backup?,expected_settings_hash?}. Ordinary existing URL-encoded endpoints remain compatible. Queue job .config is the operation snapshot; .backup is data for restore; .expected_settings_hash protects wizard commits. Maximum recovery JSON 524288 bytes; maximum containing request/job 1048576 bytes. Ordinary requests retain small limits.

Worker extension actions/functions:
- wizard-test -> draft staging, never commits Settings.
- wizard-apply -> apply draft then commit Settings only on success, serialized against direct Save Settings using STATUS/configuration.lock. Publishes settings hash and change-required state.
- backup -> export single JSON recovery document, strict allowlist (settings without token, PEM live certificate+key+chain, ACME account key only, minimal metadata). No raw acme shell configuration, logs, tokens, jobs, helpers or DSM passwords. Package-group-readable protected transfer output, never public status. CGI streams authenticated download then removes it; bounded expiry cleanup.
- restore -> validate recovery JSON and PEMs; restore app state/settings auto_renew=0 with freshly supplied cf_token, never deploy to DSM or issue. No blindly restored DSM ID; rediscover target and report conflicts. Supports backup with no certificate. Reconstruct renewal profile safely from validated certificate/config, preserve ACME account key when present.
- systemd-setup -> temporary worker startup without permanent bootstrap task, renewal timer off, bounded setup lease and cleanup path. Existing healthy permanent setup must not be disabled.
- finish-setup -> release temporary-setup state after permanent task creation; verify task before enabling normal automation.
- cancel-setup -> cleanup only wizard-owned temporary service state, after active jobs finish.
- prepare-uninstall -> no app data erasure; independent root cleanup monitor armed only after quiescence and scheduler absence. postuninst signals commit; actual protected erasure only after package removal verified. Fresh untouched uninstall allowed. Independent SSH emergency tool confirms/removes exact app-owned components, no DSM certificate deletion or global package DB edits.

Frontend: use the seven sections listed above, with certificate operations in Certificate settings, Dashboard Check Now, automatic renewal in Automation, separate Backup & Restore and Uninstall, and the optional Setup Wizard always using the same label. Wizard draft lives only in memory, starts with latest saved settings, Back retains edits, Next no commit, staging no commit, Apply & Save explicit confirmation. Existing verified worker reused. Fresh setup uses a temporary disabled scheduler task to start trusted setup service, permanent bootstrap created at end. Password re-entry is accepted when needed, never cache password/token across long setup. Temp task startup/delete and closure recovery must be explicit and independently detectable. Show current/last operation and link Logs. No raw log snippet on Dashboard.

Testing: existing full regression plus new backup secret exclusion/tampering, restore round-trip/rejection/no DSM mutation, draft isolation/conflicts, cleanup failure/bypass guards, duplicates, JS flow. Local fixtures do not certify every DSM implementation. Carry earlier native evidence forward only with clear provenance; do not relabel it as a newly executed release test.
