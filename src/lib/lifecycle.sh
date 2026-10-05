# Included in the hash-verified worker at build time. Never sourced from target.
SCHED_SETUP_NAME='SadlerACME Setup'
SCHED_SETUP_COMMAND='/bin/systemctl start pkg-sadleracme-setup.service'
REMOVAL='/usr/local/etc/sadleracme-removal'
CLEANUP_UNIT='/usr/local/lib/systemd/system/sadleracme-cleanup.service'

scheduler_read_rows() {
  # WORK is a root-private per-invocation directory. Only fixed diagnostics may
  # leave it: SQLite stderr can contain database values or scheduler commands.
  sr_db='/usr/syno/etc/esynoscheduler/esynoscheduler.db'
  sr_error="$WORK/scheduler-read.stderr"
  sr_diagnostic="$WORK/scheduler-read.diagnostic"
  : > "$sr_error"
  : > "$sr_diagnostic"
  sr_sqlite=$(command -v sqlite3 2>/dev/null || true)
  if [ -z "$sr_sqlite" ]; then
    printf '%s\n' 'tool missing (exit 127)' > "$sr_diagnostic"
    return 127
  fi
  if [ ! -r "$sr_db" ]; then
    printf '%s\n' 'access/open (exit 1)' > "$sr_diagnostic"
    return 1
  fi
  # A short-lived DSM scheduler write may hold the database lock. Wait for that
  # lock only; never retry or weaken the checks on the returned task inventory.
  if "$sr_sqlite" -readonly -cmd '.timeout 5000' -separator '|' "$sr_db" "$1" 2>"$sr_error"; then
    return 0
  else
    sr_exit=$?
  fi
  sr_detail=$(head -c 4096 "$sr_error" | LC_ALL=C tr '[:upper:]' '[:lower:]')
  case "$sr_detail" in
    *'database is locked'*|*'database table is locked'*|*'database schema is locked'*|*'database is busy'*) sr_category='busy/locked';;
    *'no such table'*|*'no such column'*|*'database schema'*|*'syntax error'*) sr_category='schema';;
    *'unable to open'*|*'cannot open'*|*'permission denied'*|*'authorization denied'*|*'not authorized'*) sr_category='access/open';;
    *) sr_category='unknown';;
  esac
  printf '%s (exit %s)\n' "$sr_category" "$sr_exit" > "$sr_diagnostic"
  return "$sr_exit"
}
scheduler_read_diagnostic() {
  # Explicit file handoff: scheduler_read_rows usually runs in $(...), so its
  # shell variables are not available to the caller.
  if [ -s "$WORK/scheduler-read.diagnostic" ]; then
    cat "$WORK/scheduler-read.diagnostic"
  else
    printf '%s\n' 'unknown (exit 1)'
  fi
}
lifecycle_task_rows() {
  # Query every match: LIMIT 1 would silently accept duplicate root tasks.
  scheduler_read_rows "SELECT task_name,enable,event,owner,operation,operation_type FROM task WHERE task_name IN ('SadlerACME Bootstrap','SadlerACME Setup') OR operation LIKE '%pkg-sadleracme-%' OR operation LIKE '%sadleracme-root%';"
}
lifecycle_tasks() {
  lt_rows=$(lifecycle_task_rows) || fail "Cannot inspect all SadlerACME scheduler tasks: $(scheduler_read_diagnostic); check DSM Task Scheduler before continuing" setup
  lt_boot_count=0; lt_setup_count=0; lt_conflict=0; lt_boot_good=0
  while IFS='|' read -r lt_name lt_enabled lt_event lt_owner lt_command lt_type; do
    [ -n "$lt_name" ] || continue
    case "$lt_name" in
      'SadlerACME Bootstrap')
        lt_boot_count=$((lt_boot_count + 1))
        if [ "$lt_enabled:$lt_event:$lt_owner:$lt_type" = '1:bootup:0:script' ] && [ "$lt_command" = "$SCHED_BOOT_COMMAND" ]; then lt_boot_good=$((lt_boot_good + 1)); else lt_conflict=1; fi
        ;;
      'SadlerACME Setup')
        lt_setup_count=$((lt_setup_count + 1))
        # The transient task must never run automatically at boot.
        [ "$lt_enabled:$lt_event:$lt_owner:$lt_type" = '0:bootup:0:script' ] && [ "$lt_command" = "$SCHED_SETUP_COMMAND" ] || lt_conflict=1
        ;;
      *) lt_conflict=1;;
    esac
  done <<TASKS
$lt_rows
TASKS
  [ "$lt_boot_count" -le 1 ] && [ "$lt_setup_count" -le 1 ] || lt_conflict=1
}
lifecycle_publish_setup() {
  if [ -f "$ROOT_STATE/setup-temporary" ]; then
    write_public setup_temporary yes
    write_public setup_expires_epoch "$(cat "$ROOT_STATE/setup-temporary")"
  else
    write_public setup_temporary no
    write_public setup_expires_epoch ''
  fi
}
lifecycle_verify_stopped() {
  for lv_unit in "$@"; do
    lv_report=$(systemctl show "$lv_unit" -p LoadState -p ActiveState 2>/dev/null) || return 1
    lv_state=$(printf '%s\n' "$lv_report" | sed -n 's/^ActiveState=//p')
    case "$lv_state" in inactive|failed) ;; *) return 1;; esac
  done
}
lifecycle_disarm_removal() {
  # Called with the worker lock before any services can be resumed. A resumed
  # installation cannot inherit an armed cleanup from an abandoned uninstall.
  # Invalidate the gate first: a failed disable/stop must not leave an old
  # positive readiness record for cleanup that is only partly armed.
  rm -f "$ROOT_STATE/uninstall-ready" || return 1
  write_public uninstall_ready no || return 1
  if [ -e "$REMOVAL" ] || [ -L "$REMOVAL" ]; then
    secure_directory "$REMOVAL" 0755
    # DSM systemd 219 has no --now; disabling alone does not stop a service.
    systemctl disable sadleracme-cleanup.service || return 1
    systemctl stop sadleracme-cleanup.service || return 1
    lifecycle_verify_stopped sadleracme-cleanup.service || return 1
    rm -f "$CLEANUP_UNIT" || return 1
    rm -rf "$REMOVAL" || return 1
    systemctl daemon-reload || return 1
  fi
}
lifecycle_resume() {
  lifecycle_disarm_removal || fail 'Unable to cancel prepared removal; use the manual recovery instructions' bootstrap
  systemctl stop pkg-sadleracme-setup-expire.timer || fail 'Unable to stop the temporary setup lease' bootstrap
  rm -f "$ROOT_STATE/setup-temporary"
  lifecycle_publish_setup
}
systemd_setup() {
  require_privileged_tools
  lifecycle_tasks
  [ "$lt_conflict" = 0 ] || fail 'Conflicting or duplicate SadlerACME scheduler tasks must be corrected before setup' setup
  if [ "$lt_boot_good" = 1 ]; then
    # This is an existing permanent installation, not wizard-owned state.
    lifecycle_disarm_removal || fail 'Unable to cancel prepared removal' setup
    chmod 1770 "$INBOX"
    systemctl start pkg-sadleracme-queue.path pkg-sadleracme-renew.timer || fail 'Unable to start existing automation' setup
    rm -f "$ROOT_STATE/setup-temporary"
    systemctl stop pkg-sadleracme-setup-expire.timer || fail 'Unable to stop the old setup lease' setup
    lifecycle_publish_setup
    scheduler_status
    write_status success 'Existing SadlerACME automation is ready; no temporary worker was needed' setup
    return
  fi
  [ "$lt_boot_count" = 0 ] || fail 'Existing bootstrap task needs correction before setup' setup
  lifecycle_disarm_removal || fail 'Unable to cancel prepared removal' setup
  chmod 1770 "$INBOX"
  systemctl stop pkg-sadleracme-renew.timer || fail 'Unable to pause the renewal timer for temporary setup' setup
  lifecycle_verify_stopped pkg-sadleracme-renew.timer || fail 'The renewal timer did not stop' setup
  # Record ownership before starting resources, so a partial start is recoverable.
  printf '%s\n' "$(( $(date +%s) + 3600 ))" > "$ROOT_STATE/setup-temporary"
  lifecycle_publish_setup
  systemctl restart pkg-sadleracme-setup-expire.timer || fail 'Unable to arm temporary worker cleanup' setup
  systemctl start pkg-sadleracme-queue.path || fail 'Unable to start the temporary queue watcher' setup
  [ "$(systemd_unit_state pkg-sadleracme-queue.path)" = active ] || fail 'The temporary queue watcher did not become active' setup
  scheduler_status
  write_status success 'Temporary setup worker is ready for up to one hour; automatic renewal is paused' setup
}
finish_setup() {
  write_status running 'Verifying permanent automation; waiting briefly if DSM scheduler is busy' setup
  lifecycle_tasks
  [ "$lt_conflict" = 0 ] && [ "$lt_boot_good" = 1 ] && [ "$lt_setup_count" = 0 ] || fail 'Install one enabled SadlerACME Bootstrap task and remove SadlerACME Setup before finishing' setup
  lifecycle_resume
  chmod 1770 "$INBOX"
  systemctl start pkg-sadleracme-queue.path pkg-sadleracme-renew.timer || fail 'Unable to start permanent automation' setup
  scheduler_status
  [ "$(systemd_unit_state pkg-sadleracme-queue.path)" = active ] && [ "$(systemd_unit_state pkg-sadleracme-renew.timer)" = active ] || fail 'Permanent automation did not become active' setup
  log 'Permanent automation verified; queue watcher and renewal timer are active'
  write_status success 'Setup complete; permanent automation is ready' setup
}
cancel_setup() {
  [ -f "$ROOT_STATE/setup-temporary" ] || { lifecycle_publish_setup; write_status success 'No temporary setup worker needs cleanup' setup; return; }
  lifecycle_tasks
  if [ "$lt_boot_good" = 1 ] && [ "$lt_boot_count" = 1 ] && [ "$lt_conflict" = 0 ]; then
    # A permanent bootstrap may have taken ownership since this wizard started.
    rm -f "$ROOT_STATE/setup-temporary"
    systemctl stop pkg-sadleracme-setup-expire.timer || fail 'Unable to stop the setup lease' setup
    lifecycle_publish_setup
    write_status success 'Temporary setup ended; existing permanent automation was preserved' setup
    return
  fi
  [ "$lt_boot_count" = 0 ] && [ "$lt_conflict" = 0 ] || fail 'Scheduler ownership is unclear; temporary cleanup stopped without changing existing automation' setup
  systemctl stop pkg-sadleracme-queue.path pkg-sadleracme-renew.timer pkg-sadleracme-setup-expire.timer || fail 'Unable to stop temporary automation; use manual recovery instructions' setup
  lifecycle_verify_stopped pkg-sadleracme-queue.path pkg-sadleracme-renew.timer || fail 'Temporary automation is still active' setup
  chmod 0700 "$INBOX"
  find "$INBOX" -mindepth 1 -maxdepth 1 \( -type f -o -type l \) -exec rm -f {} \;
  rm -f "$ROOT_STATE/setup-temporary"
  lifecycle_publish_setup
  scheduler_status
  if [ "$lt_setup_count" != 0 ]; then
    write_status error 'Temporary worker stopped. Remove the disabled SadlerACME Setup task in DSM Task Scheduler before uninstalling' setup
  else
    rm -f "$VAR/automation.requested"
    write_status success 'Temporary setup worker stopped; saved settings and certificates were retained' setup
  fi
}
setup_expired() {
  [ -f "$ROOT_STATE/setup-temporary" ] || return 0
  lease_deadline=$(cat "$ROOT_STATE/setup-temporary")
  case "$lease_deadline" in ''|*[!0-9]*) fail 'Temporary setup expiry is invalid; check setup status or use manual recovery' setup;; esac
  [ "${#lease_deadline}" -le 10 ] || fail 'Temporary setup expiry is invalid; check setup status or use manual recovery' setup
  # An expiry service can wait behind another job while a newer wizard renews
  # the lease. Check the CURRENT deadline under the lock, not the timer age.
  [ "$lease_deadline" -le "$(date +%s)" ] || return 0
  # The shared worker lock means an active certificate operation finishes before
  # expiry cleanup; renewal never starts while setup-temporary exists.
  cancel_setup
}

lifecycle_write_monitor() {
  # This helper is generated from the verified worker, never executed from a
  # package-writable payload. It survives Package Center removing package units.
  cat > "$REMOVAL/monitor.tmp" <<'MONITOR'
#!/bin/sh
set -eu
umask 077
PATH=/usr/syno/bin:/usr/syno/sbin:/usr/bin:/bin:/usr/sbin:/sbin
export PATH
BASE='/var/packages/sadleracme'
PROTECTED='/usr/local/etc/sadleracme'
REMOVAL='/usr/local/etc/sadleracme-removal'
UNIT='/usr/local/lib/systemd/system/sadleracme-cleanup.service'
[ "$(id -u)" = 0 ] || exit 1
safe_root_dir() {
  [ -d "$1" ] && [ ! -L "$1" ] && [ "$(stat -c %u "$1")" = 0 ] &&
    [ -z "$(find "$1" -maxdepth 0 \( -perm -020 -o -perm -002 \) -print)" ]
}
# @PACKAGE_STORAGE_HELPERS@
for parent in /usr /usr/local /usr/local/etc /usr/local/lib /usr/local/lib/systemd /usr/local/lib/systemd/system "$REMOVAL"; do safe_root_dir "$parent" || exit 1; done
[ -f "$REMOVAL/armed" ] && [ ! -L "$REMOVAL/armed" ] && [ "$(stat -c %u "$REMOVAL/armed")" = 0 ] || exit 1
nonce=$(cat "$REMOVAL/armed")
case "$nonce" in ''|*[!a-f0-9]*) exit 1;; esac
[ "${#nonce}" = 64 ] || exit 1
while :; do
  if [ -f "$REMOVAL/signal/commit" ] && [ ! -L "$REMOVAL/signal/commit" ] && [ "$(stat -c %s "$REMOVAL/signal/commit")" -le 80 ] && [ "$(cat "$REMOVAL/signal/commit")" = "$nonce" ] && [ ! -e "$BASE" ] && [ ! -L "$BASE" ]; then
    # This lock survives protected-data deletion so cleanup retries and the
    # emergency helper cannot remove the same storage concurrently.
    [ ! -L "$REMOVAL/cleanup.lock" ] || exit 1
    exec 8>"$REMOVAL/cleanup.lock"
    flock -w 1200 8 || exit 1
    [ ! -e "$BASE" ] && [ ! -L "$BASE" ] || { flock -u 8; exec 8>&-; continue; }
    if [ -e "$PROTECTED" ] || [ -L "$PROTECTED" ]; then
      safe_root_dir "$PROTECTED" && safe_root_dir "$PROTECTED/private" || exit 1
      exec 9>"$PROTECTED/private/worker.lock"
      flock -w 1200 9 || exit 1
      # Reinstallation and cancellation win over cleanup.
      [ ! -e "$BASE" ] && [ ! -L "$BASE" ] || { flock -u 9; exec 9>&-; flock -u 8; exec 8>&-; continue; }
      [ "$(cat "$PROTECTED/status/uninstall_ready" 2>/dev/null)" = yes ] || exit 1
    fi
    # Refuse mounts in protected state and the independent helper, including
    # retries after protected state was already removed.
    mounts=$(awk -v p="$PROTECTED" -v r="$REMOVAL" '$5==p || index($5,p "/")==1 || $5==r || index($5,r "/")==1 {print $5}' /proc/self/mountinfo) || exit 1
    [ -z "$mounts" ] || exit 1
    # DSM retains physical @appdata/@appconf directories after unlinking the
    # package. Both identities must still match this preparation before either
    # is erased. Helpers accept an already-removed leaf on a cleanup retry.
    package_storage_verify "$REMOVAL/package-var" var || exit 1
    package_storage_verify "$REMOVAL/package-etc" etc || exit 1
    if [ -e "$REMOVAL/package-etc-alias" ] || [ -L "$REMOVAL/package-etc-alias" ]; then
      [ ! -e "$REMOVAL/package-etc-alias.absent" ] && [ ! -L "$REMOVAL/package-etc-alias.absent" ] || exit 1
      package_storage_alias_verify "$REMOVAL/package-etc-alias" || exit 1
      [ "$(sed -n '4p' "$REMOVAL/package-etc-alias")" = "$(sed -n '1p' "$REMOVAL/package-etc")" ] || exit 1
    else
      # An alias which appeared after preparation has no captured identity.
      package_storage_alias_absence_verify "$REMOVAL/package-etc-alias.absent" || exit 1
    fi
    package_storage_remove "$REMOVAL/package-var" var || exit 1
    package_storage_remove "$REMOVAL/package-etc" etc || exit 1
    if [ -f "$REMOVAL/package-etc-alias" ]; then
      package_storage_alias_remove "$REMOVAL/package-etc-alias" || exit 1
    else
      package_storage_alias_absence_verify "$REMOVAL/package-etc-alias.absent" || exit 1
    fi
    if [ -e "$PROTECTED" ] || [ -L "$PROTECTED" ]; then
      rm -rf -- "$PROTECTED"
      [ ! -e "$PROTECTED" ] && [ ! -L "$PROTECTED" ] || exit 1
    fi
    systemctl disable sadleracme-cleanup.service || exit 1
    [ ! -L "$UNIT" ] || exit 1
    rm -f "$UNIT"
    rm -rf -- "$REMOVAL"
    systemctl daemon-reload
    exit 0
  fi
  sleep 5
 done
MONITOR
  chmod 0500 "$REMOVAL/monitor.tmp"
  mv -f "$REMOVAL/monitor.tmp" "$REMOVAL/monitor"
}
lifecycle_arm_removal() {
  for la_parent in /usr/local/lib /usr/local/lib/systemd /usr/local/lib/systemd/system; do
    [ -d "$la_parent" ] && [ ! -L "$la_parent" ] && [ "$(stat -c %u "$la_parent")" = 0 ] && [ -z "$(find "$la_parent" -maxdepth 0 \( -perm -020 -o -perm -002 \) -print)" ] || fail "Unsafe systemd unit directory: $la_parent" uninstall
  done
  secure_directory "$REMOVAL" 0755
  # Capture trusted physical directories while DSM's package links still
  # exist. Keep the root-owned identity records for the independent monitor;
  # preparation never erases the recorded package data.
  package_storage_capture "$VAR" var "$REMOVAL/package-var" || fail 'Cannot safely record SadlerACME package data for removal; use the Emergency SSH removal instructions' uninstall
  package_storage_capture "$ETC" etc "$REMOVAL/package-etc" || fail 'Cannot safely record SadlerACME package settings for removal; use the Emergency SSH removal instructions' uninstall
  package_storage_alias_capture "$REMOVAL/package-etc-alias" || fail 'Cannot safely record the SadlerACME DSM configuration alias; use the Emergency SSH removal instructions' uninstall
  if [ -f "$REMOVAL/package-etc-alias" ]; then
    [ "$(sed -n '4p' "$REMOVAL/package-etc-alias")" = "$(sed -n '1p' "$REMOVAL/package-etc")" ] || fail 'The SadlerACME DSM configuration alias does not match the registered settings directory; use the Emergency SSH removal instructions' uninstall
  fi
  # Re-prepare is idempotent and invalidates an earlier postuninst signal.
  if [ -e "$REMOVAL/signal" ] || [ -L "$REMOVAL/signal" ]; then
    [ -d "$REMOVAL/signal" ] && [ ! -L "$REMOVAL/signal" ] && [ "$(stat -c %u "$REMOVAL/signal")" = 0 ] || fail 'Unsafe removal signal directory' uninstall
  else mkdir "$REMOVAL/signal"; fi
  chgrp "$(stat -Lc %g "$ETC")" "$REMOVAL/signal"
  chmod 1770 "$REMOVAL/signal"
  rm -f "$REMOVAL/signal/commit"
  "$OPENSSL" rand -hex 32 > "$REMOVAL/armed.tmp"
  chmod 0644 "$REMOVAL/armed.tmp"
  mv -f "$REMOVAL/armed.tmp" "$REMOVAL/armed"
  lifecycle_write_monitor
  [ ! -L "$CLEANUP_UNIT" ] || fail 'Unsafe cleanup unit path' uninstall
  cat > "$CLEANUP_UNIT.tmp" <<'UNIT'
[Unit]
Description=Finish confirmed SadlerACME removal
After=local-fs.target
[Service]
Type=simple
User=root
Group=root
UMask=0077
ExecStart=/bin/sh /usr/local/etc/sadleracme-removal/monitor
Restart=on-failure
RestartSec=60s
NoNewPrivileges=true
[Install]
WantedBy=multi-user.target
UNIT
  chmod 0644 "$CLEANUP_UNIT.tmp"
  mv -f "$CLEANUP_UNIT.tmp" "$CLEANUP_UNIT"
  systemctl daemon-reload || fail 'Unable to load the independent cleanup service' uninstall
  systemctl enable sadleracme-cleanup.service || fail 'Unable to arm persistent uninstall cleanup' uninstall
  # A repeat preparation rotates the nonce; an already-running monitor must
  # reload it rather than waiting forever for the previous commit value.
  # restart also starts an inactive service; enable alone does not start it.
  systemctl restart sadleracme-cleanup.service || fail 'Unable to restart independent uninstall cleanup' uninstall
  [ "$(systemd_unit_state sadleracme-cleanup.service)" = active ] || fail 'Independent cleanup service did not start; uninstall remains blocked' uninstall
}
prepare_uninstall() {
  # A failed repeat preparation must not leave a previous positive gate valid.
  rm -f "$ROOT_STATE/uninstall-ready"
  write_public uninstall_ready no
  lifecycle_tasks
  [ -z "$lt_rows" ] || fail 'Remove SadlerACME Bootstrap and SadlerACME Setup tasks in DSM Task Scheduler, then prepare again' uninstall
  chmod 0700 "$INBOX"
  # Download artifacts are temporary exports, not the retained application
  # state. Remove them so an abandoned preparation cannot retain a secret copy
  # indefinitely after its expiry timer has stopped.
  if [ -d "$PROTECTED/transfers" ]; then
    [ ! -L "$PROTECTED/transfers" ] && [ "$(stat -c %u "$PROTECTED/transfers")" = 0 ] || fail 'Unsafe recovery transfer directory' uninstall
    find "$PROTECTED/transfers" -mindepth 1 -maxdepth 1 \( -type f -o -type l \) -name '*.json' -exec rm -f {} \;
    write_public backup_download ''
  fi
  systemctl disable pkg-sadleracme-transfer-expire.timer || fail 'Unable to disable recovery-download cleanup timer' uninstall
  systemctl stop pkg-sadleracme-transfer-expire.timer || fail 'Unable to stop recovery-download cleanup timer' uninstall
  systemctl stop pkg-sadleracme-queue.path pkg-sadleracme-renew.timer pkg-sadleracme-setup-expire.timer pkg-sadleracme-transfer-expire.timer || fail 'Unable to stop automation; uninstall remains blocked' uninstall
  lifecycle_verify_stopped pkg-sadleracme-queue.path pkg-sadleracme-renew.timer pkg-sadleracme-setup-expire.timer pkg-sadleracme-transfer-expire.timer || fail 'Automation is still active or its status is unknown' uninstall
  # The shared worker lock guarantees that earlier jobs have finished. Queued
  # requests are cancelled, not replayed after a future reinstall.
  find "$INBOX" -mindepth 1 -maxdepth 1 \( -type f -o -type l \) -exec rm -f {} \;
  rm -f "$ROOT_STATE/setup-temporary"
  lifecycle_publish_setup
  lifecycle_arm_removal
  rm -f "$VAR/automation.requested"
  : > "$ROOT_STATE/uninstall-ready"
  write_public uninstall_ready yes
  write_status success 'Ready to uninstall in Package Center. SadlerACME data will be deleted after confirmed removal; DSM-installed certificates are retained.' uninstall
}
