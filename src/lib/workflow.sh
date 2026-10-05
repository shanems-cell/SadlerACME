# Wizard configuration is immutable per queued job. Only successful Apply commits.
configuration_lock() {
  if [ ! -e "$STATUS_DIR/configuration.lock" ]; then
    : > "$STATUS_DIR/configuration.lock" || return 1
    chmod 0644 "$STATUS_DIR/configuration.lock" || return 1
  fi
  [ -f "$STATUS_DIR/configuration.lock" ] && [ ! -L "$STATUS_DIR/configuration.lock" ] || return 1
  exec 6<"$STATUS_DIR/configuration.lock"
  flock -x -w 10 6
}
configuration_unlock() { flock -u 6; }
settings_hash_file() { "$JQ" -cS . "$1" | sha256sum | cut -d' ' -f1; }
commit_settings_from_file() {
  commit_source="$1"
  [ -f "$commit_source" ] && [ ! -L "$commit_source" ] || return 1
  "$JQ" -e 'type=="object"' "$commit_source" >/dev/null || return 1
  # The DSM-managed etc link resolves to its package account's directory.
  # Never truncate a package-supplied settings symlink with root privileges.
  commit_parent=$(readlink -f "$ETC") || return 1
  [ -d "$commit_parent" ] || return 1
  commit_owner=$(stat -Lc '%u:%g' "$ETC") || return 1
  cp "$commit_source" "$WORK/commit-settings.json" || return 1
  chmod 0600 "$WORK/commit-settings.json" || return 1
  chown "$commit_owner" "$WORK/commit-settings.json" || return 1
  # Create with O_EXCL and write/chown via the held descriptor: the package
  # account owns this directory and could otherwise replace a pathname with
  # a symlink between mktemp and an elevated write/chown.
  commit_nonce=$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n') || return 1
  [ "${#commit_nonce}" = 32 ] || return 1
  commit_temp="$ETC/.settings-root.$commit_nonce"
  (
    set -C
    exec 5>"$commit_temp" || exit 1
    set +C
    cat "$WORK/commit-settings.json" >&5 &&
      chmod 0600 /proc/self/fd/5 && chown "$commit_owner" /proc/self/fd/5 &&
      mv -Tf "$commit_temp" "$ETC/settings.json"
  ) || { rm -f "$commit_temp"; return 1; }
}
check_expected_settings() {
  expected=$("$JQ" -r '.expected_settings_hash // ""' "$WORK/job.json")
  case "$expected" in ''|*[!0-9a-f]*) fail "Reload the wizard: its saved-settings reference is missing" wizard;; esac
  [ "${#expected}" = 64 ] && [ "$expected" = "$(settings_hash_file "$ETC/settings.json")" ] || fail "Settings changed in another window. Reopen the wizard before applying." wizard
}
run_wizard_test() {
  # run_test uses only STAGE_CFG/STAGE_CERTS and never commits CONFIG. Its
  # protected diagnostic snapshot is not an active production configuration.
  run_test
}

workflow_dsm_inventory() (
  wi_destination="$1"
  # Compare the whole DSM inventory, including default selection and actual
  # archive fingerprints. Any unreadable entry is unknown, never proof that
  # a partially failed deployment left DSM unchanged.
  /usr/syno/bin/synowebapi --exec-fastwebapi api=SYNO.Core.Certificate.CRT method=list version=1 > "$WORK/wizard-inventory.json" 2> "$WORK/wizard-inventory.stderr" || exit 1
  "$JQ" -e '.success==true and (.data.certificates|type=="array" and all((.id|type=="string" and length>0 and length<=128 and test("^[A-Za-z0-9_-]+$"))))' "$WORK/wizard-inventory.json" >/dev/null || exit 1
  "$JQ" -cS '.data.certificates|map({id,desc,is_default})|sort_by(.id)' "$WORK/wizard-inventory.json" > "$wi_destination" || exit 1
  "$JQ" -r '.data.certificates|sort_by(.id)|.[].id' "$WORK/wizard-inventory.json" > "$WORK/wizard-inventory.ids" || exit 1
  while IFS= read -r wi_id; do
    wi_fp=$(cert_fp_normalized "/usr/syno/etc/certificate/_archive/$wi_id/cert.pem") || exit 1
    case "$wi_fp" in ''|*[!0-9a-f]*) exit 1;; esac
    [ "${#wi_fp}" = 64 ] || exit 1
    printf '%s %s\n' "$wi_id" "$wi_fp" >> "$wi_destination" || exit 1
  done < "$WORK/wizard-inventory.ids"
)

workflow_snapshot_state() (
  ws_destination="$1"
  mkdir -p "$ws_destination" || exit 1
  for ws_name in live prod-config prod-certs applied_signature applied-settings.json last-settings.json dsm-id; do
    if [ -e "$ROOT_STATE/$ws_name" ] || [ -L "$ROOT_STATE/$ws_name" ]; then
      cp -a "$ROOT_STATE/$ws_name" "$ws_destination/$ws_name" || exit 1
    else
      : > "$ws_destination/absent-$ws_name" || exit 1
    fi
  done
)

workflow_restore_state() (
  ws_source="$1"
  # Copy rather than consume the snapshot: rollback itself can be interrupted
  # and retried safely. The verified worker owns every name in this list.
  for ws_name in live prod-config prod-certs applied_signature applied-settings.json last-settings.json dsm-id; do
    if [ -e "$ws_source/$ws_name" ] || [ -L "$ws_source/$ws_name" ]; then
      rm -rf "$ROOT_STATE/$ws_name" || exit 1
      cp -a "$ws_source/$ws_name" "$ROOT_STATE/$ws_name" || exit 1
    elif [ -f "$ws_source/absent-$ws_name" ]; then
      rm -rf "$ROOT_STATE/$ws_name" || exit 1
    else exit 1; fi
  done
)

workflow_retain_candidate() (
  wc_draft="$1"
  CONFIG="$wc_draft"
  KEY_TYPE=$(read_setting key_type)
  "$JQ" -r '.domains[]' "$CONFIG" > "$WORK/domains" || exit 0
  wc_live="$LIVE"
  if ! validate_certificate "$wc_live"; then
    # ACME can finish before publication of LIVE or APPLIED_SIG. Recover only
    # validated data from the fixed issued-profile filenames, never its hooks.
    wc_primary=$("$JQ" -r '.domains[0]' "$CONFIG")
    validate_domain "$wc_primary" || exit 0
    case "$KEY_TYPE" in ec-256|ec-384) wc_profile="$PROD_CERTS/${wc_primary}_ecc";; rsa-2048|rsa-4096) wc_profile="$PROD_CERTS/$wc_primary";; *) exit 0;; esac
    wc_live="$WORK/wizard-issued-candidate"
    mkdir -p "$wc_live" || exit 1
    cp "$wc_profile/$wc_primary.key" "$wc_live/key.pem" 2>/dev/null &&
      cp "$wc_profile/$wc_primary.cer" "$wc_live/cert.pem" 2>/dev/null &&
      cp "$wc_profile/ca.cer" "$wc_live/ca.pem" 2>/dev/null &&
      cp "$wc_profile/fullchain.cer" "$wc_live/fullchain.pem" 2>/dev/null || exit 0
    validate_certificate "$wc_live" || exit 0
  fi
  wc_directory=$(mktemp -d "$ROOT_STATE/wizard-retry.XXXXXXXX") || exit 1
  mkdir "$wc_directory/live" || exit 1
  for wc_pem in key.pem cert.pem ca.pem fullchain.pem; do
    cp "$wc_live/$wc_pem" "$wc_directory/live/$wc_pem" || exit 1
  done
  for wc_name in prod-config prod-certs; do
    if [ -e "$ROOT_STATE/$wc_name" ]; then cp -a "$ROOT_STATE/$wc_name" "$wc_directory/$wc_name" || exit 1; fi
  done
  printf '%s\n' "$(config_signature)" > "$wc_directory/config-signature" || exit 1
  cp "$wc_directory/config-signature" "$wc_directory/applied_signature" || exit 1
  # A partially copied directory never becomes the reusable candidate.
  rm -rf "$ROOT_STATE/wizard-retry" || exit 1
  mv -T "$wc_directory" "$ROOT_STATE/wizard-retry" || exit 1
)

workflow_seed_candidate() (
  wc_directory="$ROOT_STATE/wizard-retry"
  [ -f "$wc_directory/config-signature" ] || exit 0
  [ "$(cat "$wc_directory/config-signature")" = "$(config_signature)" ] || exit 0
  KEY_TYPE=$(read_setting key_type)
  "$JQ" -r '.domains[]' "$CONFIG" > "$WORK/domains" || exit 1
  validate_certificate "$wc_directory/live" || exit 0
  wc_generation=$(mktemp -d "$ROOT_STATE/live-gen.XXXXXXXX") || exit 1
  for wc_pem in key.pem cert.pem ca.pem fullchain.pem; do
    cp "$wc_directory/live/$wc_pem" "$wc_generation/$wc_pem" || exit 1
  done
  for wc_name in prod-config prod-certs applied_signature; do
    if [ -e "$wc_directory/$wc_name" ]; then
      rm -rf "$ROOT_STATE/$wc_name" || exit 1
      cp -a "$wc_directory/$wc_name" "$ROOT_STATE/$wc_name" || exit 1
    fi
  done
  rm -rf "$LIVE" || exit 1
  ln -s "${wc_generation##*/}" "$LIVE" || exit 1
)

workflow_apply_completed() {
  rm -rf "$ROOT_STATE/wizard-transaction" "$ROOT_STATE/wizard-retry" || return 1
  rm -f "$ROOT_STATE/wizard-apply.pending" || return 1
  write_public wizard_apply_pending no
}

workflow_recover_pending() {
  # Caller holds configuration.lock and has already recovered DSM's own file
  # transaction/reload. This function is also used after a caught Apply error.
  wf_transaction="$ROOT_STATE/wizard-transaction"
  if [ ! -e "$wf_transaction" ]; then
    if [ -f "$ROOT_STATE/wizard-apply.pending" ]; then
      write_public wizard_apply_pending yes
      write_status error "Wizard application recovery is incomplete. Automatic renewal is paused; use Issue / Apply to reconcile the saved settings." wizard-apply
    fi
    return 0
  fi
  [ -d "$wf_transaction" ] && [ ! -L "$wf_transaction" ] && [ "$(stat -c %u "$wf_transaction")" = 0 ] || return 1
  if [ ! -f "$wf_transaction/started" ]; then rm -rf "$wf_transaction"; return; fi
  if [ -f "$wf_transaction/committed" ]; then workflow_apply_completed; return; fi
  # A crash can occur just after settings were atomically committed. A saved
  # deployed marker plus exact configuration match completes that commit.
  if [ -f "$wf_transaction/deployed" ] && [ "$(settings_hash_file "$ETC/settings.json")" = "$(settings_hash_file "$wf_transaction/draft.json")" ]; then
    workflow_apply_completed
    return
  fi
  if [ -f "$wf_transaction/rolled-back" ]; then
    rm -f "$ROOT_STATE/wizard-apply.pending"
    write_public wizard_apply_pending no
    rm -rf "$wf_transaction"
    return
  fi
  if [ ! -f "$wf_transaction/inherited-pending" ] && [ -f "$wf_transaction/before-dsm.complete" ] &&
      [ ! -e "$ROOT_STATE/transaction.pending" ] && [ ! -e "$ROOT_STATE/reload.pending" ] &&
      [ ! -e "$ROOT_STATE/deployment-history.pending" ] &&
      workflow_dsm_inventory "$WORK/wizard-after-dsm" && cmp -s "$wf_transaction/before-dsm" "$WORK/wizard-after-dsm"; then
    # Retain an already issued, validated candidate before restoring active
    # state, allowing a deliberate retry without another ACME request.
    workflow_retain_candidate "$wf_transaction/draft.json" || return 1
    workflow_restore_state "$wf_transaction/old" || return 1
    : > "$wf_transaction/rolled-back" || return 1
    rm -f "$ROOT_STATE/wizard-apply.pending"
    write_public wizard_apply_pending no
    refresh_cert_metadata
    publish_applied_signature
    write_status error "Wizard Apply did not complete. DSM is unchanged and the previous certificate configuration was restored. Retry Apply & Save to reuse any valid issued certificate." wizard-apply
    rm -rf "$wf_transaction"
  else
    : > "$ROOT_STATE/wizard-apply.pending" || return 1
    write_public wizard_apply_pending yes
    write_public next_auto_epoch ""
    write_status error "Wizard Apply did not complete and DSM may already contain the new certificate. Saved settings were not changed. Automatic renewal is paused; retry Apply & Save or use Issue / Apply to reconcile." wizard-apply
  fi
}

run_wizard_apply() {
  configuration_lock || fail "Settings are busy; retry" wizard
  check_expected_settings
  # Renewal is enabled explicitly after the permanent bootstrap is verified.
  "$JQ" '.auto_renew="0"' "$CONFIG" > "$WORK/wizard-apply.json"
  CONFIG="$WORK/wizard-apply.json"
  wf_inherited_pending=0
  if [ -e "$ROOT_STATE/wizard-transaction" ]; then
    # Existing uncertain deployment is retained as the active candidate; a
    # deliberate retry starts from it and never rolls back past that boundary.
    workflow_recover_pending || fail "Cannot recover the previous wizard application; automatic renewal remains paused" wizard
    if [ -e "$ROOT_STATE/wizard-transaction" ]; then
      wf_inherited_pending=1
      workflow_retain_candidate "$ROOT_STATE/wizard-transaction/draft.json" || fail "Cannot preserve the pending certificate for retry" wizard
      rm -rf "$ROOT_STATE/wizard-transaction" || fail "Cannot replace the previous wizard recovery record" wizard
    fi
  fi
  [ ! -f "$ROOT_STATE/wizard-apply.pending" ] || wf_inherited_pending=1
  wf_transaction="$ROOT_STATE/wizard-transaction"
  mkdir -p "$wf_transaction" || fail "Cannot create wizard recovery record" wizard
  [ "$wf_inherited_pending" = 0 ] || : > "$wf_transaction/inherited-pending"
  cp "$CONFIG" "$wf_transaction/draft.json" && workflow_snapshot_state "$wf_transaction/old" || fail "Cannot preserve the active certificate configuration before Apply" wizard
  if workflow_dsm_inventory "$wf_transaction/before-dsm"; then : > "$wf_transaction/before-dsm.complete"; fi
  : > "$wf_transaction/started"
  : > "$ROOT_STATE/wizard-apply.pending"
  write_public wizard_apply_pending yes
  workflow_seed_candidate || fail "Cannot prepare the saved certificate candidate; recovery will run before further work" wizard
  # A directly executed subshell preserves errexit semantics inside the old
  # production path. `if (run_apply)` would suppress its checked shell exits.
  set +e
  (
    set -e
    trap - EXIT HUP INT TERM
    run_apply
  )
  wf_apply_result=$?
  set -e
  if [ "$wf_apply_result" -ne 0 ]; then
    workflow_recover_pending || fail "Wizard Apply failed and its state could not be restored. Automatic renewal remains paused." wizard
    ERROR_REPORTED=1
    exit 1
  fi
  : > "$wf_transaction/deployed"
  if ! commit_settings_from_file "$CONFIG"; then
    write_public wizard_apply_pending yes
    write_public next_auto_epoch ""
    fail "Certificate applied, but saving settings failed. Automatic renewal is paused. Keep this wizard open and retry Apply & Save; the valid certificate will be reused." wizard
  fi
  : > "$wf_transaction/committed"
  workflow_apply_completed || fail "Settings saved, but wizard recovery cleanup failed; reopen the app before further changes" wizard
  publish_applied_signature
  write_public restore_requires_issue no
  write_public settings_pending no
  write_status success "Certificate applied and settings saved. Complete Automation to enable renewal." wizard-apply
  configuration_unlock
}
run_restore() {
  configuration_lock || fail "Settings are busy; retry" restore
  check_expected_settings
  [ ! -e "$ROOT_STATE/wizard-transaction" ] && [ ! -f "$ROOT_STATE/wizard-apply.pending" ] || fail "A previous wizard Apply needs recovery. Reconcile it with Apply & Save or Issue / Apply before restoring a backup." restore
  restore_backup
  workflow_apply_completed || fail "Backup restored, but old wizard recovery cleanup failed; reopen the app before further changes" restore
  publish_applied_signature
  configuration_unlock
}
workflow_initialise() {
  configuration_lock || fail "Cannot lock configuration recovery" recovery
  recovery_recover_transaction || fail "An interrupted restore could not be recovered; protected data was retained" recovery
  configuration_unlock
  recovery_expire_transfers
  lifecycle_publish_setup
}

workflow_job_receipt() {
  case "$ACTIVE_JOB" in *.job) receipt_stem=${ACTIVE_JOB%.job};; *) return 1;; esac
  case "$receipt_stem" in ''|*[!0-9a-f-]*) return 1;; esac
  [ "${#ACTIVE_JOB}" -le 80 ] || return 1
  receipt_result=failed; [ "$1" -ne 0 ] || receipt_result=completed
  [ "${2:-}" != interrupted ] || receipt_result=interrupted
  mkdir -p "$STATUS_DIR/jobs" || return 1
  chmod 0755 "$STATUS_DIR/jobs" || return 1
  "$JQ" -n --arg id "$ACTIVE_JOB" --arg result "$receipt_result" \
    --arg message "$(read_status_value message)" \
    '{ok:true,job_id:$id,result:$result,message:$message}' > "$STATUS_DIR/jobs/$ACTIVE_JOB.json.tmp" || return 1
  chmod 0644 "$STATUS_DIR/jobs/$ACTIVE_JOB.json.tmp" && mv -f "$STATUS_DIR/jobs/$ACTIVE_JOB.json.tmp" "$STATUS_DIR/jobs/$ACTIVE_JOB.json" || return 1
  # Only our validated queue IDs are receipt filenames; keep the latest 50.
  find "$STATUS_DIR/jobs" -maxdepth 1 -type f -name '*.job.json' | sort -r | tail -n +51 | while IFS= read -r old_receipt; do rm -f "$old_receipt"; done
}
