# Assembled into index.cgi. All routes run after DSM administrator authentication.
api_json() {
  printf 'Content-Type: application/json; charset=utf-8\r\nCache-Control: no-store\r\n\r\n'
  printf '%s\n' "$1"
  exit 0
}
api_failure() {
  printf 'Status: %s\r\n' "$1"
  printf '%s' "$2" | "$JQ" -Rs --arg code "${3:-}" '{ok:false,message:.} + (if $code=="" then {} else {code:$code} end)' > "$API_WORK/error.json"
  api_json "$(cat "$API_WORK/error.json")"
}
api_settings_hash() { printf '%s' "$SETTINGS_DATA" | "$JQ" -cS . | sha256sum | cut -d' ' -f1; }
api_config_lock() {
  if [ -f "$STATUS/configuration.lock" ] && [ ! -L "$STATUS/configuration.lock" ]; then
    exec 6<"$STATUS/configuration.lock" || return 1
    flock -xn 6 || return 1
  fi
}
api_queue() {
  api_action="$1"
  API_QUEUE_CODE=''
  [ -f "$VAR/package.running" ] || { FLASH="Package is stopped"; return 1; }
  [ "$(read_status uninstall_ready)" != yes ] || { FLASH="Uninstall is prepared; restart the bootstrap task to resume"; return 1; }
  # This rejection happens before creating a job. The wizard can safely offer
  # worker recovery, followed by an explicit retry of the original operation.
  [ -d "$QUEUE_DIR" ] && [ -w "$QUEUE_DIR" ] || { API_QUEUE_CODE=worker_unavailable; FLASH="Background processing is unavailable. Restart the worker in Setup Wizard, or start it from Automation."; return 1; }
  exec 7>"$ETC/queue.lock" || return 1
  flock -w 5 7 || { FLASH="Queue is busy; retry"; return 1; }
  api_count=$(find "$QUEUE_DIR" -maxdepth 1 -name '*.job' | wc -l)
  [ "$api_count" -lt 5 ] || { FLASH="Five jobs are queued; wait for completion"; return 1; }
  api_random=$(od -An -N12 -tx1 /dev/urandom | tr -d ' \n')
  [ "${#api_random}" = 24 ] || { FLASH="Secure random source failed"; return 1; }
  api_sequence=0
  [ ! -f "$ETC/queue.sequence" ] || api_sequence=$(cat "$ETC/queue.sequence")
  case "$api_sequence" in ''|*[!0-9]*) api_sequence=0;; esac
  [ "${#api_sequence}" -le 11 ] || api_sequence=0
  api_sequence=$((api_sequence + 1))
  printf '%s\n' "$api_sequence" > "$ETC/queue.sequence.tmp" && mv -f "$ETC/queue.sequence.tmp" "$ETC/queue.sequence" || return 1
  JOB_ID="$(printf '%012d' "$api_sequence")-$api_random.job"
  api_tmp=$(mktemp "$QUEUE_DIR/.new.XXXXXXXX") || return 1
  "$JQ" --arg action "$api_action" --slurpfile config "$API_WORK/config.json" \
    '{action:$action,config:$config[0]} + (if has("backup") then {backup:.backup} else {} end) +
     (if has("expected_settings_hash") then {expected_settings_hash:.expected_settings_hash} else {} end) +
     (if has("transfer_id") then {transfer_id:.transfer_id} else {} end)' "$API_WORK/request.json" > "$api_tmp" &&
    chmod 0600 "$api_tmp" && mv -f "$api_tmp" "$QUEUE_DIR/$JOB_ID" || { rm -f "$api_tmp"; FLASH="Cannot commit request"; return 1; }
  flock -u 7
  FLASH="Action queued: $api_action"
}
api_normalize_config() {
  # Explicit fields only: a restored document cannot introduce execution hooks.
  "$JQ" '{email:(.email // ""), domains:(.domains // []),key_type:(.key_type // "ec-384"),
    cert_desc:(.cert_desc // "SadlerACME wildcard"),cf_token:(.cf_token // ""),
    default_on_create:(if .default_on_create=="1" then "1" else "0" end),
    auto_renew:(if .auto_renew=="1" then "1" else "0" end),dns_sleep:(.dns_sleep // "60")}' "$API_WORK/rawconfig.json" > "$API_WORK/config.json" || return 1
  "$JQ" -e 'type=="object" and ([.email,.key_type,.cert_desc,.cf_token,.dns_sleep]|all(type=="string")) and
    (.email|test("\\A[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}\\z")) and
    (.domains|type=="array" and length>0 and length<=100 and all(type=="string" and length<=253 and test("^(\\*\\.)?([a-z0-9]([a-z0-9-]*[a-z0-9])?\\.)+[a-z]{2,}$"))) and
    (.key_type=="ec-256" or .key_type=="ec-384" or .key_type=="rsa-2048" or .key_type=="rsa-4096") and
    (.cert_desc|length>0 and length<=80) and (.cf_token=="" or (.cf_token|test("^[A-Za-z0-9_-]{20,256}$"))) and
    (.dns_sleep|test("^[0-9]{2,3}$") and (tonumber>=30 and tonumber<=600))' "$API_WORK/config.json" >/dev/null
}
api_download() {
  transfer=$("$JQ" -r '.transfer_id // ""' "$API_WORK/request.json")
  case "$transfer" in ''|*[!0-9a-f-]*) api_failure '400 Bad Request' 'Invalid backup download reference';; esac
  [ "${#transfer}" -le 80 ] || api_failure '400 Bad Request' 'Invalid backup download reference'
  archive="$PROTECTED/transfers/$transfer.json"
  [ -f "$archive" ] && [ ! -L "$archive" ] && [ "$(stat -c %u "$archive")" = 0 ] || api_failure '410 Gone' 'Backup download expired or is unavailable. Create a new backup.'
  [ "$(stat -c %s "$archive")" -le 524288 ] || api_failure '500 Internal Server Error' 'Backup exceeds the supported size'
  age=$(($(date +%s) - $(stat -c %Y "$archive")))
  [ "$age" -ge 0 ] && [ "$age" -lt 900 ] || api_failure '410 Gone' 'Backup download expired. Create a new backup.'
  printf 'Content-Type: application/json\r\nContent-Disposition: attachment; filename="SadlerACME-Recovery.json"\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\n\r\n'
  cat "$archive"
  # A closed connection must not retain the archive indefinitely. This is
  # best-effort immediate cleanup; the independent expiry timer is the fallback.
  api_queue backup-delete >/dev/null 2>&1 || true
  exit 0
}
workflow_api_request() {
  if [ "${REQUEST_METHOD:-GET}" = GET ] && [ "$(query_value api)" = job ]; then
    receipt_id=$(query_value id)
    case "$receipt_id" in *.job) receipt_stem=${receipt_id%.job};; *) http_error '400 Bad Request' 'Invalid job reference';; esac
    case "$receipt_stem" in ''|*[!0-9a-f-]*) http_error '400 Bad Request' 'Invalid job reference';; esac
    [ "${#receipt_id}" -le 80 ] || http_error '400 Bad Request' 'Invalid job reference'
    receipt="$STATUS/jobs/$receipt_id.json"
    if [ -f "$receipt" ] && [ ! -L "$receipt" ]; then
      api_json "$(cat "$receipt")"
    fi
    api_json "$(printf '%s' "$receipt_id" | "$JQ" -Rs '{ok:true,job_id:.,result:"pending",message:"Waiting for worker completion"}')"
  fi
  if [ "${REQUEST_METHOD:-GET}" = GET ] && [ "$(query_value api)" = settings ]; then
    printf '%s' "$SETTINGS_DATA" | "$JQ" --arg hash "$(api_settings_hash)" '{ok:true,config:del(.cf_token),has_token:((.cf_token // "")|length>0),settings_hash:$hash}' | {
      printf 'Content-Type: application/json; charset=utf-8\r\nCache-Control: no-store\r\n\r\n'; cat;
    }
    exit 0
  fi
  case "${REQUEST_METHOD:-GET}:${CONTENT_TYPE:-}" in POST:application/json*) ;; *) return 0;; esac
  len=${CONTENT_LENGTH:-0}
  case "$len" in ''|*[!0-9]*) http_error '400 Bad Request' 'Invalid request length';; esac
  [ "${#len}" -le 7 ] && [ "$len" -gt 0 ] && [ "$len" -le 1048576 ] || http_error '413 Payload Too Large' 'Recovery request is too large'
  API_WORK=$(mktemp -d "$ETC/.api.XXXXXXXX") || http_error '503 Service Unavailable' 'Cannot create request workspace'
  trap 'rm -rf "$API_WORK"' EXIT
  dd bs=1 count="$len" of="$API_WORK/request.json" 2>/dev/null || api_failure '400 Bad Request' 'Cannot read request'
  [ "$(stat -c %s "$API_WORK/request.json")" = "$len" ] || api_failure '400 Bad Request' 'Incomplete request'
  "$JQ" -e 'type=="object" and (.action|type=="string") and (.csrf|type=="string")' "$API_WORK/request.json" >/dev/null 2>&1 || api_failure '400 Bad Request' 'Malformed JSON request'
  [ "$("$JQ" -r .csrf "$API_WORK/request.json")" = "$(cat "$TOKEN_FILE")" ] || api_failure '403 Forbidden' 'Security token mismatch; reload the app'
  action=$("$JQ" -r .action "$API_WORK/request.json")
  case "$action" in restore) ;; *) [ "$len" -le 32768 ] || api_failure '413 Payload Too Large' 'Request is too large';; esac
  printf '%s' "$SETTINGS_DATA" > "$API_WORK/config.json"
  case "$action" in
    automation-intent)
      : > "$VAR/automation.requested" || api_failure '503 Service Unavailable' 'Cannot record automation setup; no task should be created'
      api_json '{"ok":true}';;
    save-auto)
      api_config_lock || api_failure '409 Conflict' 'A configuration operation is running; wait for completion'
      exec 8>"$ETC/settings.lock"; flock -w 5 8 || api_failure '409 Conflict' 'Settings are busy'
      SETTINGS_DATA=$(cat "$ETC/settings.json")
      [ "$("$JQ" -r '.expected_settings_hash // ""' "$API_WORK/request.json")" = "$(api_settings_hash)" ] || api_failure '409 Conflict' 'Settings changed; reload before enabling renewal'
      auto=$("$JQ" -r '.auto_renew // ""' "$API_WORK/request.json")
      case "$auto" in 0|1) ;; *) api_failure '400 Bad Request' 'Choose whether to enable renewal';; esac
      if [ "$auto" = 1 ]; then
        [ "$(read_status scheduler_status)" = 'Installed and enabled' ] && [ "$(read_status setup_temporary)" != yes ] && [ "$(read_status uninstall_ready)" != yes ] || api_failure '409 Conflict' 'Verify the permanent bootstrap task before enabling renewal'
        [ "$(read_status wizard_apply_pending)" != yes ] && [ "$(read_status restore_requires_issue)" != yes ] || api_failure '409 Conflict' 'Complete certificate application or recovery before enabling renewal'
        saved_signature=$(printf '%s' "$SETTINGS_DATA" | "$JQ" -cS '{domains,key_type}' | sha256sum | cut -d' ' -f1)
        [ "$saved_signature" = "$(read_status applied_signature)" ] || api_failure '409 Conflict' 'Issue / Apply the saved certificate settings before enabling renewal'
      fi
      saved_tmp=$(mktemp "$ETC/settings.XXXXXXXX") || api_failure '503 Service Unavailable' 'Cannot save settings'
      printf '%s' "$SETTINGS_DATA" | "$JQ" --arg auto "$auto" '.auto_renew=$auto' > "$saved_tmp" && chmod 0600 "$saved_tmp" && mv -f "$saved_tmp" "$ETC/settings.json" || { rm -f "$saved_tmp"; api_failure '503 Service Unavailable' 'Cannot save settings'; }
      # Saving the preference does not start a renewal or reset its timer.
      # Refresh the worker's timer/certificate status using the committed settings.
      # A full/unavailable queue must not turn a completed save into a save error.
      if { cp "$ETC/settings.json" "$API_WORK/config.json" && api_queue refresh; } >/dev/null 2>&1; then
        api_json '{"ok":true,"message":"Automatic renewal setting saved","status_refresh_queued":true}'
      fi
      api_json '{"ok":true,"message":"Automatic renewal setting saved. Status refresh is pending; use Check Scheduler Status to retry.","status_refresh_queued":false}';;
    download-backup) api_download;;
    wizard-test|wizard-apply)
      "$JQ" '.config' "$API_WORK/request.json" > "$API_WORK/rawconfig.json"
      api_normalize_config || api_failure '400 Bad Request' 'Check the certificate settings and Cloudflare token'
      if [ "$action" != restore ] && [ -z "$("$JQ" -r .cf_token "$API_WORK/config.json")" ]; then
        printf '%s' "$SETTINGS_DATA" > "$API_WORK/saved.json"
        "$JQ" --slurpfile saved "$API_WORK/saved.json" '.cf_token=$saved[0].cf_token' "$API_WORK/config.json" > "$API_WORK/merged.json" && mv "$API_WORK/merged.json" "$API_WORK/config.json"
      fi
      [ -n "$("$JQ" -r '.cf_token // ""' "$API_WORK/config.json")" ] || api_failure '400 Bad Request' 'Enter the Cloudflare token; it is not included in backups'
      ;;
    restore)
      "$JQ" -e '(.backup|type=="object") and (.config.cf_token|type=="string" and test("^[A-Za-z0-9_-]{20,256}$"))' "$API_WORK/request.json" >/dev/null 2>&1 || api_failure '400 Bad Request' 'Select a recovery backup and enter the Cloudflare token'
      "$JQ" '.config' "$API_WORK/request.json" > "$API_WORK/config.json"
      ;;
    backup|backup-delete|finish-setup|cancel-setup|prepare-uninstall|redeploy|refresh|scheduler-status|check|clear-log) ;;
    *) api_failure '400 Bad Request' 'Unknown workflow action';;
  esac
  api_queue "$action" || api_failure '409 Conflict' "${FLASH:-Cannot queue operation}" "${API_QUEUE_CODE:-}"
  printf '%s' "$FLASH" | "$JQ" -Rs --arg id "$JOB_ID" '{ok:true,message:.,job_id:$id}' > "$API_WORK/result.json"
  api_json "$(cat "$API_WORK/result.json")"
}
