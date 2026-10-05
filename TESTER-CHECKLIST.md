# Public-beta tester checklist — SadlerACME 1.0.0-1

Use this checklist for a deliberate evaluation. It is not a requirement to repeat working certificate or destructive recovery operations after every documentation update. Record Pass, Fail or Not tested, with environment and timestamp.

| Area | Observation to record |
| --- | --- |
| Install/open | Exact package version and checksum; prerequisites and administrator session work without bypasses |
| Existing installation | Settings and DSM assignments retained; no unrequested certificate issuance |
| Interface | Default Dashboard in a new session, remembered size/position, readable theme and reachable controls |
| Guided setup | Draft edits remain separate from saved settings; temporary/permanent worker state is clearly identified |
| Staging, only when intended | Outcome and log; production settings and DSM certificate unchanged |
| Production, only when explicitly intended | Issuance/reuse and deployment outcome, served certificate and DSM assignments |
| Renewal | Distinguish non-due checks from naturally due renewal; record unattended outcomes separately |
| Backup/restore, only when intended | Secure completed export; no credentials in backup; explicit restore without automatic deployment |
| Uninstall, disposable/recoverable systems only | Preparation, task/helper shutdown, readiness and cleanup; DSM certificate retained |
| Logs | Independent scrolling, readable messages, no secrets in shared reports |

For this release promotion, the owner's immediate check is only the installation/open/help check in RELEASE-GUIDE.md. Emergency root scheduler-API operations, DSM upgrades and additional model coverage require their own evidence; do not assume a pass from a different route or model.
