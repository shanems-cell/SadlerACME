#!/bin/sh
# SadlerACME — original project by Shane Sadler
# Copyright (C) 2026 Shane Sadler
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE and NOTICE.txt in the source distribution.
set -u
set -f
umask 077
PATH=/usr/syno/bin:/usr/syno/sbin:/usr/bin:/bin:/usr/sbin:/sbin
LC_ALL=C
export PATH LC_ALL
PKG=sadleracme
BASE=/var/packages/sadleracme
ETC="$BASE/etc"
VAR="$BASE/var"
PROTECTED=/usr/local/etc/sadleracme
STATUS="$PROTECTED/status"
QUEUE_DIR="$PROTECTED/inbox"
LOG="$STATUS/log"
VERSION="1.0.0-1"
SCHED_BOOT_NAME="SadlerACME Bootstrap"
SCHED_BOOT_COMMAND="/bin/systemctl start pkg-sadleracme-bootstrap.service"

http_error() {
  printf 'Status: %s\r\nContent-Type: text/plain; charset=utf-8\r\nCache-Control: no-store\r\n\r\n%s\n' "$1" "$2"
  exit 0
}
# Apply DSM session authentication to HTML, status and every POST action.
AUTH=/usr/syno/synoman/webman/modules/authenticate.cgi
[ -x "$AUTH" ] || http_error '503 Service Unavailable' 'DSM authentication helper is unavailable'
# Authenticate from the request's cookie/token without letting the helper
# consume a POST body that belongs to parse_post. Overrides affect only it.
auth_rc=0
DSM_USER=$(REQUEST_METHOD=GET CONTENT_LENGTH=0 "$AUTH" </dev/null 2>/dev/null) || auth_rc=$?
[ "$auth_rc" = 0 ] || http_error '401 Unauthorized' "DSM session check failed (helper exit $auth_rc). Refresh the DSM desktop and reopen SadlerACME."
[ -n "$DSM_USER" ] || http_error '401 Unauthorized' 'DSM session was not accepted. Refresh the DSM desktop and reopen SadlerACME from its main menu while signed in as an administrator.'
case "$DSM_USER" in -*|*'
'*) http_error '403 Forbidden' 'Invalid DSM identity';; esac
id -Gn "$DSM_USER" 2>/dev/null | tr ' ' '\n' | grep -Fxq administrators || http_error '403 Forbidden' 'DSM administrator access is required'
JQ=$(command -v jq) || http_error '503 Service Unavailable' 'jq is required'
TOKEN_FILE="$ETC/ui_csrf.$(printf '%s' "$DSM_USER" | sha256sum | cut -d' ' -f1)"

html_escape() {
  printf '%s' "$1" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g; s/"/\&quot;/g; s/'"'"'/\&#39;/g'
}
json_escape() { "$JQ" -Rs . | sed 's/^"//;s/"$//'; }
json_value() { printf '%s' "$1" | json_escape; }
url_decode() {
  printf '%s' "$1" | awk '
    function hex(c) { return index("0123456789abcdef",tolower(c))-1 }
    { for(i=1;i<=length($0);i++) {
      c=substr($0,i,1)
      if(c=="+") printf " "
      else if(c=="%") {
        a=hex(substr($0,i+1,1)); b=hex(substr($0,i+2,1))
        if(i+2>length($0)||a<0||b<0) exit 1
        n=a*16+b
        if(n==0||n==127||(n<32&&n!=9&&n!=10&&n!=13)) exit 1
        printf "%c",n; i+=2
      } else printf "%s",c
    }}'
}
query_value() (
  # The status route must accept DSM's token alongside api=status.
  query_key="$1"; IFS='&'
  for query_pair in ${QUERY_STRING:-}; do
    query_name=$(url_decode "${query_pair%%=*}") || return 1
    if [ "$query_name" = "$query_key" ]; then
      url_decode "${query_pair#*=}"
      return
    fi
  done
)
read_setting() {
  printf '%s' "$SETTINGS_DATA" | "$JQ" -r --arg key "$1" '.[$key] // "" | if type=="array" then join("\n") else tostring end'
}
read_status() { [ ! -f "$STATUS/$1" ] || cat "$STATUS/$1"; }
ensure_csrf() {
  if [ ! -s "$TOKEN_FILE" ]; then
    token_tmp=$(mktemp "$ETC/csrf.XXXXXXXX") || return 1
    od -An -N24 -tx1 /dev/urandom | tr -d ' \n' > "$token_tmp"
    [ "$(wc -c < "$token_tmp")" -eq 48 ] || { rm -f "$token_tmp"; return 1; }
    ln "$token_tmp" "$TOKEN_FILE" 2>/dev/null || true
    rm -f "$token_tmp"
  fi
  [ -s "$TOKEN_FILE" ] && [ ! -L "$TOKEN_FILE" ]
}
load_settings() {
  exec 8>"$ETC/settings.lock" || return 1
  flock -w 5 8 || return 1
  if [ ! -f "$ETC/settings.json" ]; then
    settings_tmp=$(mktemp "$ETC/settings.XXXXXXXX") || return 1
    for field in email domains key_type cert_desc cf_token default_on_create auto_renew; do
      [ ! -f "$ETC/$field" ] || head -c 16384 "$ETC/$field"
      printf '\000'
    done | "$JQ" -Rs 'split("\u0000") | {email:.[0]|rtrimstr("\n"),domains:(.[1]|split("\n")|map(select(length>0))),key_type:(.[2]|rtrimstr("\n")|if length>0 then . else "ec-384" end),cert_desc:(.[3]|rtrimstr("\n")|if length>0 then . else "SadlerACME wildcard" end),cf_token:.[4]|rtrimstr("\n"),default_on_create:(.[5]|rtrimstr("\n")|if .=="1" then "1" else "0" end),auto_renew:(.[6]|rtrimstr("\n")|if .=="0" then "0" else "1" end),dns_sleep:"60"}' > "$settings_tmp" || return 1
    chmod 0600 "$settings_tmp" && mv -f "$settings_tmp" "$ETC/settings.json" || return 1
    # Remove obsolete credential copies only after atomic conversion succeeded.
    rm -f "$ETC/email" "$ETC/domains" "$ETC/key_type" "$ETC/cert_desc" "$ETC/cf_token" "$ETC/default_on_create" "$ETC/auto_renew" "$ETC/ui_csrf"
  fi
  SETTINGS_DATA=$(cat "$ETC/settings.json") || return 1
  printf '%s' "$SETTINGS_DATA" | "$JQ" -e 'type=="object"' >/dev/null || return 1
  flock -u 8
}
parse_post() {
  POST_ACTION=""; P_CSRF=""; P_EMAIL=""; P_DOMAINS=""; P_KEY=""; P_DESC=""; P_TOKEN=""; P_DEFAULT="0"; P_AUTO="0"; P_DNS_SLEEP="60"
  len=${CONTENT_LENGTH:-0}
  case "$len" in *[!0-9]*|'') return 1;; esac
  [ "${#len}" -le 5 ] && [ "$len" -gt 0 ] && [ "$len" -le 16384 ] || return 1
  case "${CONTENT_TYPE:-}" in application/x-www-form-urlencoded*) ;; *) return 1;; esac
  data=$(dd bs=1 count="$len" 2>/dev/null) || return 1
  oldifs=$IFS; IFS='&'
  for pair in $data; do
    key=${pair%%=*}; val=${pair#*=}
    key=$(url_decode "$key") && val=$(url_decode "$val") || { IFS=$oldifs; return 1; }
    case "$key" in
      action) POST_ACTION="$val";; csrf) P_CSRF="$val";; email) P_EMAIL="$val";; domains) P_DOMAINS="$val";;
      key_type) P_KEY="$val";; cert_desc) P_DESC="$val";; cf_token) P_TOKEN="$val";;
      default_on_create) P_DEFAULT="$val";; auto_renew) P_AUTO="$val";; dns_sleep) P_DNS_SLEEP="$val";;
    esac
  done
  IFS=$oldifs
}

save_config() {
  api_config_lock || { FLASH="A configuration operation is running; wait for completion"; return 1; }
  printf '%s' "$P_EMAIL" | "$JQ" -Rse 'test("\\A[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}\\z")' >/dev/null || { FLASH="Email address is not valid"; return 1; }
  case "$P_KEY" in ec-256|ec-384|rsa-2048|rsa-4096) ;; *) FLASH="Invalid key type"; return 1;; esac
  [ -n "$P_DESC" ] && [ "${#P_DESC}" -le 80 ] || { FLASH="Certificate description must be 1–80 characters"; return 1; }
  case "$P_DNS_SLEEP" in *[!0-9]*|'') FLASH="DNS wait must be 30–600 seconds"; return 1;; esac
  [ "$P_DNS_SLEEP" -ge 30 ] && [ "$P_DNS_SLEEP" -le 600 ] || { FLASH="DNS wait must be 30–600 seconds"; return 1; }
  exec 8>"$ETC/settings.lock" || return 1
  flock -w 5 8 || { FLASH="Settings are busy; retry"; return 1; }
  # Retaining a blank token reads the most recently committed settings.
  if [ -z "$P_TOKEN" ]; then P_TOKEN=$("$JQ" -r '.cf_token // ""' "$ETC/settings.json"); fi
  if [ -n "$P_TOKEN" ]; then printf '%s' "$P_TOKEN" | grep -Eq '^[A-Za-z0-9_-]{20,256}$' || { FLASH="Cloudflare token format is invalid"; return 1; }; fi
  tmp=$(mktemp "$ETC/settings.XXXXXXXX") || { FLASH="Cannot create settings file"; return 1; }
  # Secrets are supplied over stdin, never as command-line arguments.
  printf '%s\000' "$P_EMAIL" "$P_DOMAINS" "$P_KEY" "$P_DESC" "$P_TOKEN" "$P_DEFAULT" "$P_AUTO" "$P_DNS_SLEEP" |
    "$JQ" -Rs 'split("\u0000") | {email:.[0],domains:(.[1]|gsub("\r";"")|split(",")|join("\n")|split("\n")|map(gsub("^\\s+|\\s+$";"")|ascii_downcase)|map(select(length>0))|reduce .[] as $d ([]; if index($d) then . else .+[$d] end)),key_type:.[2],cert_desc:.[3],cf_token:.[4],default_on_create:(if .[5]=="1" then "1" else "0" end),auto_renew:(if .[6]=="1" then "1" else "0" end),dns_sleep:.[7]}' > "$tmp" || { rm -f "$tmp"; FLASH="Cannot encode Settings"; return 1; }
  "$JQ" -e '.domains|length>0 and length<=100 and all(length<=253 and test("^(\\*\\.)?([a-z0-9]([a-z0-9-]*[a-z0-9])?\\.)+[a-z]{2,}$"))' "$tmp" >/dev/null || { rm -f "$tmp"; FLASH="Enter 1–100 valid DNS names"; return 1; }
  chmod 0600 "$tmp" && mv -f "$tmp" "$ETC/settings.json" || { rm -f "$tmp"; FLASH="Settings could not be saved"; return 1; }
  SETTINGS_DATA=$(cat "$ETC/settings.json")
  flock -u 8
  if [ -n "$(read_status applied_signature)" ] && [ "$(printf '%s' "$SETTINGS_DATA" | "$JQ" -cS '{domains,key_type}' | sha256sum | cut -d' ' -f1)" != "$(read_status applied_signature)" ]; then
    FLASH="Settings saved — Issue / Apply is required before automatic renewal"
  else FLASH="Settings saved"; fi
}
queue_action() {
  [ -f "$VAR/package.running" ] || { FLASH="Package is stopped"; return 1; }
  [ -d "$QUEUE_DIR" ] && [ -w "$QUEUE_DIR" ] || { FLASH="Open Automation and install or update the bootstrap task, then run it once"; return 1; }
  [ "$(read_status uninstall_ready)" != yes ] || { FLASH="Uninstall is prepared; install/run the bootstrap task to resume"; return 1; }
  exec 7>"$ETC/queue.lock" || return 1
  flock -w 5 7 || { FLASH="Queue is busy; retry"; return 1; }
  # Bound the queue; each request carries an immutable configuration snapshot.
  count=$(find "$QUEUE_DIR" -maxdepth 1 -name '*.job' | wc -l)
  [ "$count" -lt 5 ] || { FLASH="Five jobs are already queued; wait for completion"; return 1; }
  random=$(od -An -N12 -tx1 /dev/urandom | tr -d ' \n')
  [ "${#random}" -eq 24 ] || { FLASH="Secure random source failed"; return 1; }
  sequence=0
  [ ! -f "$ETC/queue.sequence" ] || sequence=$(cat "$ETC/queue.sequence")
  case "$sequence" in ''|*[!0-9]*) sequence=0;; esac
  [ "${#sequence}" -le 11 ] || sequence=0
  sequence=$((sequence + 1))
  printf '%s\n' "$sequence" > "$ETC/queue.sequence.tmp" && mv -f "$ETC/queue.sequence.tmp" "$ETC/queue.sequence" || { FLASH="Cannot allocate queue sequence"; return 1; }
  JOB_ID="$(printf '%012d' "$sequence")-$random.job"
  tmp=$(mktemp "$QUEUE_DIR/.new.XXXXXXXX") || { FLASH="Cannot write queue"; return 1; }
  printf '%s' "$SETTINGS_DATA" | "$JQ" --arg action "$1" '{action:$action,config:.}' > "$tmp" &&
    chmod 0600 "$tmp" && mv -f "$tmp" "$QUEUE_DIR/$JOB_ID" || { rm -f "$tmp"; FLASH="Cannot commit queued job"; return 1; }
  flock -u 7
  FLASH="Action queued: $1"
}
key_label() {
  case "$1" in
    ec-384) printf 'ECC P-384' ;;
    ec-256) printf 'ECC P-256' ;;
    rsa-4096) printf 'RSA 4096' ;;
    rsa-2048) printf 'RSA 2048' ;;
    *) printf '%s' "$1" ;;
  esac
}
pretty_yes_no() {
  case "$1" in
    true|1|yes|Yes) printf 'Yes' ;;
    false|0|no|No) printf 'No' ;;
    '') printf 'Unknown' ;;
    *) printf '%s' "$1" ;;
  esac
}
clean_log() {
  [ -f "$LOG" ] || return 0
  tail -n 350 "$LOG" | awk '
    /-----BEGIN CERTIFICATE-----/ { if(!pem) print "[certificate PEM omitted]"; pem=1; next }
    /-----END CERTIFICATE-----/ { pem=0; next }
    !pem { print }
  '
}


# @CGI_EXTENSIONS@

mkdir -p "$ETC" "$VAR" || http_error '503 Service Unavailable' 'Settings directory is unavailable'
load_settings || http_error '503 Service Unavailable' 'Settings could not be read or migrated'
ensure_csrf || http_error '503 Service Unavailable' 'Cannot create a secure session token'
FLASH=""; JOB_ID=""
workflow_api_request
case "${REQUEST_METHOD:-GET}" in
  GET) ;;
  POST)
    parse_post || http_error '400 Bad Request' 'Malformed or oversized request'
    csrf=$(cat "$TOKEN_FILE")
    [ -n "$P_CSRF" ] && [ "$P_CSRF" = "$csrf" ] || http_error '403 Forbidden' 'Security token mismatch; reload the page'
    ok=true
    case "$POST_ACTION" in
      save) save_config || ok=false;;
      test|apply|check|force|redeploy|scheduler-status|refresh|clear-log|prepare-uninstall) queue_action "$POST_ACTION" || ok=false;;
      *) http_error '400 Bad Request' 'Unknown action';;
    esac
    if [ "$POST_ACTION" != save ]; then
      [ "$ok" = true ] || printf 'Status: 409 Conflict\r\n'
      printf 'Content-Type: application/json; charset=utf-8\r\nCache-Control: no-store\r\n\r\n'
      printf '{"ok":%s,"message":"%s","job_id":"%s"}\n' "$ok" "$(json_value "$FLASH")" "$JOB_ID"
      exit 0
    fi
    ;;
  *) http_error '405 Method Not Allowed' 'Only GET and POST are supported';;
esac

EMAIL=$(read_setting email)
DOMAINS=$(read_setting domains)
KEY=$(read_setting key_type); [ -n "$KEY" ] || KEY="ec-384"
KEYLABEL=$(key_label "$KEY")
DESC=$(read_setting cert_desc); [ -n "$DESC" ] || DESC="SadlerACME wildcard"
HAS_TOKEN="No"; [ -z "$(read_setting cf_token)" ] || HAS_TOKEN="Yes"
DNS_SLEEP=$(read_setting dns_sleep); DNS_SLEEP=${DNS_SLEEP:-60}
DEF=$(read_setting default_on_create); AUTO=$(read_setting auto_renew)
STATE=$(read_status state); [ -n "$STATE" ] || STATE="idle"
MESSAGE=$(read_status message); [ -n "$MESSAGE" ] || MESSAGE="Waiting for configuration"
LAST=$(read_status last_run); [ -n "$LAST" ] || LAST="Never"
LAST_ACTION=$(read_status last_action); [ -n "$LAST_ACTION" ] || LAST_ACTION="None"
WORKER_LAST=$(read_status worker_last_seen); [ -n "$WORKER_LAST" ] || WORKER_LAST="Not detected yet"
WORKER_EPOCH=$(read_status worker_last_seen_epoch)
CERT_SUBJECT=$(read_status cert_subject); [ -n "$CERT_SUBJECT" ] || CERT_SUBJECT="Not issued yet"
CERT_ISSUER=$(read_status cert_issuer); [ -n "$CERT_ISSUER" ] || CERT_ISSUER="—"
CERT_SERIAL=$(read_status cert_serial); [ -n "$CERT_SERIAL" ] || CERT_SERIAL="—"
CERT_FP=$(read_status cert_fingerprint); [ -n "$CERT_FP" ] || CERT_FP="—"
CERT_NB=$(read_status cert_not_before); [ -n "$CERT_NB" ] || CERT_NB="—"
CERT_NA=$(read_status cert_not_after); [ -n "$CERT_NA" ] || CERT_NA="—"
CERT_SANS=$(read_status cert_sans); [ -n "$CERT_SANS" ] || CERT_SANS="—"
CERT_DAYS=$(read_status cert_days_remaining); [ -n "$CERT_DAYS" ] || CERT_DAYS="—"
DSM_ID=$(read_status dsm_cert_id); [ -n "$DSM_ID" ] || DSM_ID="—"
DSM_DEFAULT_RAW=$(read_status dsm_default)
DSM_DEFAULT=$(pretty_yes_no "$DSM_DEFAULT_RAW")
DSM_MATCH=$(read_status dsm_match); [ -n "$DSM_MATCH" ] || DSM_MATCH="unknown"
case "$DSM_DEFAULT_RAW" in
  true|1|yes|Yes) DEFAULT_ROLE_CLASS="good"; DEFAULT_ROLE_TEXT="Default certificate" ;;
  false|0|no|No) DEFAULT_ROLE_CLASS="muted"; DEFAULT_ROLE_TEXT="Not the DSM default" ;;
  *) DEFAULT_ROLE_CLASS="muted"; DEFAULT_ROLE_TEXT="Not yet determined" ;;
esac
DEPLOY_METHOD=$(read_status deployment_method); [ -n "$DEPLOY_METHOD" ] || DEPLOY_METHOD="Not recorded"
MAILPLUS_RELOAD=$(read_status mailplus_reload); [ -n "$MAILPLUS_RELOAD" ] || MAILPLUS_RELOAD="Not required yet"
LAST_ISSUE=$(read_status last_issue); [ -n "$LAST_ISSUE" ] || LAST_ISSUE="Not recorded"
LAST_RENEW=$(read_status last_renewal); [ -n "$LAST_RENEW" ] || LAST_RENEW="Not recorded"
LAST_DEPLOY=$(read_status last_deploy); [ -n "$LAST_DEPLOY" ] || LAST_DEPLOY="Not recorded"
LAST_VERIFIED=$(read_status last_verified); [ -n "$LAST_VERIFIED" ] || LAST_VERIFIED="Not recorded"
LAST_STAGING=$(read_status last_staging); [ -n "$LAST_STAGING" ] || LAST_STAGING="Not recorded"
NEXT_AUTO_EPOCH=$(read_status next_auto_epoch)
SCHED_STATUS=$(read_status scheduler_status); [ -n "$SCHED_STATUS" ] || SCHED_STATUS="Not checked"
SCHED_DETAIL=$(read_status scheduler_detail); [ -n "$SCHED_DETAIL" ] || SCHED_DETAIL="Run a scheduler status check to inspect DSM Task Scheduler integration"
SCHED_EVENT=$(read_status scheduler_event); [ -n "$SCHED_EVENT" ] || SCHED_EVENT="—"
SCHED_OWNER=$(read_status scheduler_owner); [ -n "$SCHED_OWNER" ] || SCHED_OWNER="—"
SCHED_COMMAND=$(read_status scheduler_command); [ -n "$SCHED_COMMAND" ] || SCHED_COMMAND="—"
SCHED_LAST=$(read_status scheduler_last_check); [ -n "$SCHED_LAST" ] || SCHED_LAST="Never"

# The Automation banner always reflects the most recently checked scheduler
# state rather than a previous action result.  JavaScript applies the same
# mapping during live status refreshes.
SCHED_BANNER_CLASS=""
SCHED_BANNER_TEXT="Scheduler status has not been checked yet. Use Check Scheduler Status to inspect the DSM boot-up task."
case "$SCHED_STATUS" in
  "Installed and enabled")
    SCHED_BANNER_CLASS="ok"
    SCHED_BANNER_TEXT="SadlerACME Bootstrap is installed, enabled and ready."
    ;;
  "Installed but disabled")
    SCHED_BANNER_CLASS="warn"
    SCHED_BANNER_TEXT="SadlerACME Bootstrap is installed but disabled. To keep SadlerACME automatic renewal and worker services available after a restart, open DSM Task Scheduler and enable ‘SadlerACME Bootstrap’."
    ;;
  "Missing")
    SCHED_BANNER_CLASS="warn"
    SCHED_BANNER_TEXT="SadlerACME Bootstrap is not installed. Use Install Scheduler Task to restore automatic startup."
    ;;
  "Incorrect configuration")
    SCHED_BANNER_CLASS="err"
    SCHED_BANNER_TEXT="SadlerACME Bootstrap exists but does not match the expected root boot-up configuration. Correct or remove the task in DSM Task Scheduler, then check the scheduler status again."
    ;;
  "Detected — details unavailable")
    SCHED_BANNER_CLASS="warn"
    SCHED_BANNER_TEXT="SadlerACME Bootstrap was detected, but DSM did not provide enough detail to verify its configuration."
    ;;
  "Unable to inspect")
    SCHED_BANNER_CLASS="err"
    SCHED_BANNER_TEXT="SadlerACME could not inspect DSM Task Scheduler. Check the scheduler status again or use the manual setup instructions."
    ;;
esac
QUEUE_STATE=$(read_status systemd_queue_state); [ -n "$QUEUE_STATE" ] || QUEUE_STATE="Unknown"
TIMER_STATE=$(read_status systemd_timer_state); [ -n "$TIMER_STATE" ] || TIMER_STATE="Unknown"
# A cached deadline is meaningful only while its timer is reported active.
[ "$TIMER_STATE" = active ] || NEXT_AUTO_EPOCH=""
case "$NEXT_AUTO_EPOCH" in ''|*[!0-9]*) NEXT_AUTO_EPOCH="";; esac
if [ -n "$NEXT_AUTO_EPOCH" ]; then
  [ "${#NEXT_AUTO_EPOCH}" -le 10 ] && [ "$NEXT_AUTO_EPOCH" -gt 0 ] || NEXT_AUTO_EPOCH=""
fi
# Expired cached deadlines are not upcoming checks. Never invent a replacement.
SERVER_EPOCH=$(date +%s)
NEXT_AUTO_STALE=no
if [ -n "$NEXT_AUTO_EPOCH" ] && [ "$NEXT_AUTO_EPOCH" -le "$SERVER_EPOCH" ]; then
  NEXT_AUTO_EPOCH=""; NEXT_AUTO_STALE=yes
fi
# Keep historical operation results separate from current certificate health.
CHECKED=$(read_status dsm_checked_epoch)
case "$CHECKED" in ''|*[!0-9]*) CHECKED=0;; esac
[ "${#CHECKED}" -le 10 ] || CHECKED=0
DSM_FRESHNESS=unverified
FRESHNESS_TEXT="DSM status has not been checked yet."
if [ "$CHECKED" -gt 0 ]; then
  DSM_FRESHNESS=fresh
  FRESHNESS_TEXT="Live status updates automatically."
  if [ $((SERVER_EPOCH - CHECKED)) -gt 120 ] || [ $((CHECKED - SERVER_EPOCH)) -gt 120 ]; then
    DSM_FRESHNESS=stale
    FRESHNESS_TEXT="Status needs refresh. The last operation result is shown above."
  fi
fi
if [ "$DSM_FRESHNESS" != fresh ]; then
  DSM_MATCH=unknown; DSM_DEFAULT=Unknown; DSM_DEFAULT_RAW=unknown
  DEFAULT_ROLE_CLASS=muted
  if [ "$DSM_FRESHNESS" = stale ]; then
    DSM_DEFAULT="Status needs refresh"; DEFAULT_ROLE_TEXT="Status needs refresh"
  else DEFAULT_ROLE_TEXT="Not yet determined"; fi
fi
# The CGI owns no root status files. Queue/busy state is derived read-only.
if [ -n "$(read_status active_job)" ]; then
  STATE=running
elif [ -d "$QUEUE_DIR" ] && [ -n "$(find "$QUEUE_DIR" -maxdepth 1 -name '*.job' -print -quit 2>/dev/null)" ]; then
  STATE=queued; MESSAGE="Waiting for the privileged worker"
fi
CSRF=$(cat "$TOKEN_FILE")
LOGTAIL=$(clean_log)
LOCAL_CERT_AVAILABLE=$(read_status local_cert_available); [ -n "$LOCAL_CERT_AVAILABLE" ] || LOCAL_CERT_AVAILABLE="unknown"

case "$STATE" in
  success) BADGE_CLASS="ok" ;;
  running) BADGE_CLASS="run" ;;
  queued) BADGE_CLASS="queue" ;;
  error) BADGE_CLASS="bad" ;;
  *) BADGE_CLASS="idle" ;;
esac
case "$DSM_MATCH" in
  yes) MATCH_CLASS="good"; MATCH_TEXT="Verified — certificate matches" ;;
  no) MATCH_CLASS="badtext"; MATCH_TEXT="Mismatch — certificate differs" ;;
  'not found') MATCH_CLASS="badtext"; MATCH_TEXT="Certificate not found in DSM" ;;
  *) MATCH_CLASS="muted"; MATCH_TEXT="Not yet verified"; [ "$DSM_FRESHNESS" != stale ] || MATCH_TEXT="Status needs refresh" ;;
esac
if [ "$AUTO" = "1" ]; then
  # The saved preference is not evidence that automation is running. Publish
  # this same label in the status API so initial rendering and polling agree.
  AUTO_TEXT="Enabled — setup required"
  if [ "$(read_status uninstall_ready)" = yes ]; then
    AUTO_TEXT="Enabled — paused for removal"
  elif [ ! -f "$VAR/package.running" ]; then
    AUTO_TEXT="Enabled — package stopped"
  elif [ "$(read_status setup_temporary)" != yes ]; then
    case "$TIMER_STATE" in
      inactive|failed) AUTO_TEXT="Enabled — timer $TIMER_STATE" ;;
      active)
        if [ "$QUEUE_STATE" = active ]; then
          case "$SCHED_STATUS" in
            "Installed and enabled") AUTO_TEXT="Enabled — every 6 hours" ;;
            "Installed but disabled") AUTO_TEXT="Enabled — boot task disabled" ;;
            "Missing"|"Incorrect configuration"|"Ambiguous tasks") ;;
            *) AUTO_TEXT="Enabled — startup unverified" ;;
          esac
        else
          case "$QUEUE_STATE" in
            inactive|failed) AUTO_TEXT="Enabled — queue $QUEUE_STATE" ;;
            *) AUTO_TEXT="Enabled — queue status unknown" ;;
          esac
        fi
        ;;
    esac
  fi
  if [ "$NEXT_AUTO_STALE" = yes ]; then
    NEXT_AUTO_TEXT="Status needs refresh"
    FRESHNESS_TEXT="Status needs refresh. Waiting for the next check time from the renewal timer."
  elif [ -n "$NEXT_AUTO_EPOCH" ]; then
    NEXT_AUTO_TEXT="Calculating…"
  elif [ "$TIMER_STATE" = inactive ] || [ "$TIMER_STATE" = failed ]; then
    NEXT_AUTO_TEXT="Timer $TIMER_STATE"
  else
    NEXT_AUTO_TEXT="Waiting for timer status"
  fi
else
  AUTO=0
  AUTO_TEXT="Disabled"
  # The timer's last published estimate can outlive a Settings change.
  NEXT_AUTO_EPOCH=""
  NEXT_AUTO_TEXT="Disabled"
  NEXT_AUTO_STALE=no
fi

SETTINGS_PENDING=no
if [ -n "$(read_status applied_signature)" ] && [ "$(printf '%s' "$SETTINGS_DATA" | "$JQ" -cS '{domains,key_type}' | sha256sum | cut -d' ' -f1)" != "$(read_status applied_signature)" ]; then SETTINGS_PENDING=yes; fi
# Empty-install display hint only; never substitutes for worker/auth checks.
SETUP_REQUIRED=no
if [ -z "$DOMAINS" ] && [ "$HAS_TOKEN" = No ] && [ "$WORKER_LAST" = "Not detected yet" ] && [ "$LOCAL_CERT_AVAILABLE" != yes ]; then
  SETUP_REQUIRED=yes
fi
if [ "$(query_value api)" = status ]; then
  printf 'Content-Type: application/json; charset=utf-8\r\n'
  printf 'Cache-Control: no-store\r\n\r\n'
  printf '{'
  for public_field in backup_download setup_temporary uninstall_ready setup_expires_epoch restore_requires_issue wizard_apply_pending; do
    printf '"%s":"%s",' "$public_field" "$(json_value "$(read_status "$public_field")")"
  done
  PACKAGE_RUNNING=no; [ ! -f "$VAR/package.running" ] || PACKAGE_RUNNING=yes
  WORKER_AVAILABLE=no
  if [ -d "$QUEUE_DIR" ] && [ -w "$QUEUE_DIR" ] && [ "$PACKAGE_RUNNING" = yes ]; then WORKER_AVAILABLE=yes; fi
  printf '"setup_required":"%s",' "$SETUP_REQUIRED"
  printf '"package_running":"%s",' "$PACKAGE_RUNNING"
  printf '"worker_available":"%s",' "$WORKER_AVAILABLE"
  printf '"settings_pending":"%s",' "$SETTINGS_PENDING"
  printf '"checked_epoch":"%s",' "$CHECKED"
  printf '"server_epoch":"%s",' "$SERVER_EPOCH"
  printf '"dsm_freshness":"%s",' "$DSM_FRESHNESS"
  printf '"next_auto_stale":"%s",' "$NEXT_AUTO_STALE"
  printf '"next_auto_text":"%s",' "$(json_value "$NEXT_AUTO_TEXT")"
  printf '"active_job":"%s",' "$(json_value "$(read_status active_job)")"
  printf '"last_job":"%s",' "$(json_value "$(read_status last_job)")"
  printf '"last_job_result":"%s",' "$(json_value "$(read_status last_job_result)")"
  printf '"state":"%s",' "$(json_value "$STATE")"
  printf '"message":"%s",' "$(json_value "$MESSAGE")"
  printf '"last_action":"%s",' "$(json_value "$LAST_ACTION")"
  printf '"last_run":"%s",' "$(json_value "$LAST")"
  printf '"worker_last":"%s",' "$(json_value "$WORKER_LAST")"
  printf '"worker_epoch":"%s",' "$(json_value "$WORKER_EPOCH")"
  printf '"issuer":"%s",' "$(json_value "$CERT_ISSUER")"
  printf '"not_before":"%s",' "$(json_value "$CERT_NB")"
  printf '"not_after":"%s",' "$(json_value "$CERT_NA")"
  printf '"days":"%s",' "$(json_value "$CERT_DAYS")"
  printf '"sans":"%s",' "$(json_value "$CERT_SANS")"
  printf '"fingerprint":"%s",' "$(json_value "$CERT_FP")"
  printf '"dsm_id":"%s",' "$(json_value "$DSM_ID")"
  printf '"dsm_default":"%s",' "$(json_value "$DSM_DEFAULT")"
  printf '"dsm_default_raw":"%s",' "$(json_value "$DSM_DEFAULT_RAW")"
  printf '"dsm_match":"%s",' "$(json_value "$DSM_MATCH")"
  printf '"local_cert_available":"%s",' "$(json_value "$LOCAL_CERT_AVAILABLE")"
  printf '"deployment_method":"%s",' "$(json_value "$DEPLOY_METHOD")"
  printf '"mailplus_reload":"%s",' "$(json_value "$MAILPLUS_RELOAD")"
  printf '"auto_renew":"%s",' "$AUTO"
  printf '"auto_renew_text":"%s",' "$(json_value "$AUTO_TEXT")"
  printf '"next_auto":"%s",' "$(json_value "$NEXT_AUTO_EPOCH")"
  printf '"last_issue":"%s",' "$(json_value "$LAST_ISSUE")"
  printf '"last_renewal":"%s",' "$(json_value "$LAST_RENEW")"
  printf '"last_deploy":"%s",' "$(json_value "$LAST_DEPLOY")"
  printf '"last_verified":"%s",' "$(json_value "$LAST_VERIFIED")"
  printf '"last_staging":"%s",' "$(json_value "$LAST_STAGING")"
  printf '"scheduler_status":"%s",' "$(json_value "$SCHED_STATUS")"
  printf '"scheduler_detail":"%s",' "$(json_value "$SCHED_DETAIL")"
  printf '"scheduler_last":"%s",' "$(json_value "$SCHED_LAST")"
  printf '"queue_state":"%s",' "$(json_value "$QUEUE_STATE")"
  printf '"timer_state":"%s",' "$(json_value "$TIMER_STATE")"
  printf '"log":"%s"' "$(json_value "$LOGTAIL")"
  printf '}\n'
  exit 0
fi

printf 'Content-Type: text/html; charset=utf-8\r\n'
printf 'Cache-Control: no-store\r\nReferrer-Policy: no-referrer\r\n\r\n'
cat <<EOF2
<!doctype html><html><head><meta charset="utf-8"><title>SadlerACME</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark"><script src="theme.js?v=$VERSION"></script>
<link rel="stylesheet" href="layout.css?v=$VERSION"><link rel="stylesheet" href="workflow.css?v=$VERSION"></head><body><div class="wrap">
<div class="head"><div class="head-start"><div><div class="title">SadlerACME</div><div class="sub">Synology DNS-01 certificate manager · v$VERSION</div><div class="muted small">Original project by Shane Sadler · GPLv3</div></div></div><div class="head-actions"><button id="themeToggle" type="button" class="btn secondary theme-toggle" aria-label="Switch to light mode" title="Switch to light mode"><svg class="nav-icon theme-icon-light" aria-hidden="true"><use href="nav-icons.svg#sun"></use></svg><svg class="nav-icon theme-icon-dark" aria-hidden="true"><use href="nav-icons.svg#moon"></use></svg><span class="theme-label">Light mode</span></button><div id="stateBadge" class="badge $BADGE_CLASS">$(html_escape "$STATE")</div><button id="menuToggle" class="btn secondary nav-toggle" type="button" aria-expanded="false" aria-controls="appNavigation" aria-label="Show navigation menu" title="Menu"><svg class="nav-icon" aria-hidden="true"><use href="nav-icons.svg#menu"></use></svg></button></div></div>
<nav class="topnav tabs" id="appNavigation" aria-label="SadlerACME pages"><div class="nav-group">
<button type="button" class="tabbtn active" data-tab="dashboard" aria-current="page"><svg class="nav-icon" aria-hidden="true"><use href="nav-icons.svg#dashboard"></use></svg><span>Dashboard</span></button>
<button type="button" class="tabbtn" data-tab="settings"><svg class="nav-icon" aria-hidden="true"><use href="nav-icons.svg#settings"></use></svg><span>Certificate settings</span></button>
<button type="button" class="tabbtn" data-tab="automation"><svg class="nav-icon" aria-hidden="true"><use href="nav-icons.svg#automation"></use></svg><span>Automation</span></button>
<button type="button" class="tabbtn" data-tab="backup"><svg class="nav-icon" aria-hidden="true"><use href="nav-icons.svg#backup"></use></svg><span>Backup &amp; Restore</span></button>
<button type="button" class="tabbtn" data-tab="uninstall"><svg class="nav-icon" aria-hidden="true"><use href="nav-icons.svg#uninstall"></use></svg><span>Uninstall</span></button>
<button type="button" class="tabbtn" data-tab="logs"><svg class="nav-icon" aria-hidden="true"><use href="nav-icons.svg#logs"></use></svg><span>Logs</span></button>
<button type="button" class="tabbtn" data-tab="about"><svg class="nav-icon" aria-hidden="true"><use href="nav-icons.svg#about"></use></svg><span>Help &amp; About</span></button>
</div></nav><div class="app-layout"><main class="content" id="mainContent">

EOF2
[ -n "$FLASH" ] && printf '<div class="card flash"><b>%s</b></div>\n' "$(html_escape "$FLASH")"
cat <<EOF2
<div id="tab-dashboard" class="tabpane active">
  <div class="page-heading with-actions"><div><h1>Dashboard</h1><p>Certificate health, DSM deployment and renewal status.</p></div><div class="wizard-heading-actions"></div></div>
  <div class="card statuscard dashboard-status"><div class="status-summary"><div id="statusMessage" class="statusline">$(html_escape "$MESSAGE")</div><div class="muted small">Last action: <span id="lastAction">$(html_escape "$LAST_ACTION")</span> · Last run: <span id="lastRun">$(html_escape "$LAST")</span></div></div><div class="status-tools"><span id="statusFreshness" class="muted small" role="status" aria-live="polite">$(html_escape "$FRESHNESS_TEXT")</span><button id="statusRefreshBtn" type="button" class="btn secondary">Refresh status</button><button id="viewLogBtn" class="btn secondary" type="button">View log</button></div></div>
  <div class="dashboard">
    <div class="card"><h2>Certificate</h2><div class="kvgrid">
      <div class="k">DSM description</div><div id="configuredDescription" class="v">$(html_escape "$DESC")</div>
      <div class="k">Configured domains</div><div id="configuredDomains" class="v multiline">$(html_escape "$DOMAINS")</div>
      <div class="k">Key</div><div id="configuredKey" class="v">$(html_escape "$KEYLABEL")</div>
      <div class="k">Issuer</div><div id="certIssuer" class="v">$(html_escape "$CERT_ISSUER")</div>
      <div class="k">Valid from</div><div id="certFrom" class="v">$(html_escape "$CERT_NB")</div>
      <div class="k">Expires</div><div id="certExpires" class="v">$(html_escape "$CERT_NA")</div>
      <div class="k">Time remaining</div><div class="v"><b id="certDays">$( [ "$CERT_DAYS" = "—" ] && printf "—" || printf "%s days" "$(html_escape "$CERT_DAYS")" )</b></div>
      <div class="k">SANs</div><div id="certSans" class="v">$(html_escape "$CERT_SANS")</div>
      <div class="k">SHA-256</div><div id="certFingerprint" class="v small">$(html_escape "$CERT_FP")</div>
    </div></div>
    <div class="card"><h2>DSM deployment</h2><div class="kvgrid">
      <div class="k">Certificate ID</div><div id="dsmId" class="v">$(html_escape "$DSM_ID")</div>
      <div class="k">Certificate match</div><div id="dsmMatch" class="v $MATCH_CLASS">$(html_escape "$MATCH_TEXT")</div>
      <div class="k">DSM default</div><div id="dsmDefault" class="v">$(html_escape "$DSM_DEFAULT")</div>
      <div class="k">Default state</div><div id="dsmDefaultState" class="v $DEFAULT_ROLE_CLASS">$(html_escape "$DEFAULT_ROLE_TEXT")</div>
      <div class="k">Method</div><div id="deployMethod" class="v">$(html_escape "$DEPLOY_METHOD")</div>
      <div class="k">MailPlus reload</div><div id="mailplusReload" class="v">$(html_escape "$MAILPLUS_RELOAD")</div>
      <div class="k">Last deployment</div><div id="lastDeploy" class="v">$(html_escape "$LAST_DEPLOY")</div>
      <div class="k">Last verified</div><div id="lastVerified" class="v">$(html_escape "$LAST_VERIFIED")</div>
    </div></div>
    <div class="card"><h2>Renewal & worker</h2><div class="kvgrid">
      <div class="k">Automatic renewal</div><div id="autoRenew" class="v">$(html_escape "$AUTO_TEXT")</div>
      <div class="k">Next check</div><div class="v"><span id="nextAuto" data-epoch="$(html_escape "$NEXT_AUTO_EPOCH")" data-enabled="$AUTO" data-timer="$(html_escape "$TIMER_STATE")" data-stale="$NEXT_AUTO_STALE" data-server-epoch="$SERVER_EPOCH">$(html_escape "$NEXT_AUTO_TEXT")</span></div>
      <div class="k">Last issue</div><div id="lastIssue" class="v">$(html_escape "$LAST_ISSUE")</div>
      <div class="k">Last renewal</div><div id="lastRenewal" class="v">$(html_escape "$LAST_RENEW")</div>
      <div class="k">Last staging test</div><div id="lastStaging" class="v">$(html_escape "$LAST_STAGING")</div>
      <div class="k">Root worker</div><div id="workerLast" class="v">$(html_escape "$WORKER_LAST")</div>
      <div class="k">Scheduler</div><div id="schedulerSummary" class="v">$(html_escape "$SCHED_STATUS")</div>
      <div class="k">Queue watcher</div><div id="queueState" class="v">$(html_escape "$QUEUE_STATE")</div>
      <div class="k">Renewal timer</div><div id="timerState" class="v">$(html_escape "$TIMER_STATE")</div>
      <div class="k">Cloudflare</div><div id="configuredToken" class="v">Token configured: $(html_escape "$HAS_TOKEN")</div>
    </div><div class="card-footer renewal-actions"><form class="actionForm" method="post"><input type="hidden" name="csrf" value="$(html_escape "$CSRF")"><input type="hidden" name="action" value="check"><button class="btn secondary">Check Now</button></form><span class="muted small">Can renew and deploy when renewal is due.</span></div></div>
  </div>
</div>

<div id="tab-settings" class="tabpane">
  <div class="page-heading with-actions"><div><h1>Certificate settings</h1><p>Save settings directly, or use Setup Wizard for guided setup and recovery.</p></div><div class="wizard-heading-actions"></div></div>
  <div class="card"><h2>Certificate & DNS settings</h2><form id="certificateSettings" method="post"><input type="hidden" name="csrf" value="$(html_escape "$CSRF")"><input type="hidden" name="action" value="save"><div class="settingsgrid certificate-grid">
    <div class="cert-description"><label for="certDescription">DSM certificate description</label><input id="certDescription" name="cert_desc" value="$(html_escape "$DESC")"></div>
    <div class="cert-key"><label for="certKey">Key type</label><select id="certKey" name="key_type">
EOF2
for opt in ec-384 ec-256 rsa-4096 rsa-2048; do
  label=$(key_label "$opt")
  sel=""; [ "$KEY" = "$opt" ] && sel=" selected"
  printf '<option value="%s"%s>%s</option>' "$opt" "$sel" "$label"
done
cat <<EOF2
    </select></div>
    <div class="cert-domains"><label for="certDomains">Domains / SANs — one per line</label><textarea id="certDomains" name="domains" placeholder="example.com&#10;*.example.com">$(html_escape "$DOMAINS")</textarea></div>
    <div class="cert-options"><div><label for="certDns">DNS propagation wait (seconds)</label><input id="certDns" name="dns_sleep" type="number" min="30" max="600" value="$(html_escape "$DNS_SLEEP")"></div><div class="check"><input type="checkbox" id="def" name="default_on_create" value="1"$([ "$DEF" = "1" ] && printf ' checked')><label for="def">Set as default only when creating a new DSM certificate</label></div></div>
    <div class="cert-email"><label for="certEmail">ACME account email</label><input id="certEmail" name="email" value="$(html_escape "$EMAIL")" placeholder="you@example.com"></div>
    <div class="cert-token"><label for="certToken">Cloudflare API token</label><input id="certToken" type="password" name="cf_token" value="" autocomplete="new-password" placeholder="Leave blank to keep saved token"><div class="muted small field-help">Token saved: $HAS_TOKEN</div></div>
    <input type="hidden" id="settingsAuto" name="auto_renew" value="$AUTO">
    <div class="cert-save"><button class="btn" type="submit">Save settings</button></div>
  </div></form></div>
  <div id="certificateOperations" class="card actionsCard"><h2>Certificate actions</h2><div class="certificate-action-line"><div class="actions">
    <form class="actionForm" method="post"><input type="hidden" name="csrf" value="$(html_escape "$CSRF")"><input type="hidden" name="action" value="test"><button class="btn secondary">Staging Test</button></form>
    <form class="actionForm" method="post"><input type="hidden" name="csrf" value="$(html_escape "$CSRF")"><input type="hidden" name="action" value="apply"><button class="btn">Issue / Apply</button></form>
    <form id="redeployForm" class="actionForm redeployForm" method="post"$([ "$DSM_MATCH" = "not found" ] && [ "$LOCAL_CERT_AVAILABLE" = "yes" ] || printf ' style="display:none"')><input type="hidden" name="csrf" value="$(html_escape "$CSRF")"><input type="hidden" name="action" value="redeploy"><button class="btn">Re-deploy Existing</button></form>
    
    <form class="actionForm forceForm" method="post"><input type="hidden" name="csrf" value="$(html_escape "$CSRF")"><input type="hidden" name="action" value="force"><button class="btn warn">Renew Early</button></form>
  </div><div class="muted action-explanation"><b>Staging Test</b> validates without deployment. <b>Issue / Apply</b> reuses or issues a certificate. <b>Renew Early</b> forces new issuance.</div></div>
  <div id="redeployNotice" class="inlineStatus warn$([ "$DSM_MATCH" = "not found" ] && [ "$LOCAL_CERT_AVAILABLE" = "yes" ] && printf ' show')">The SadlerACME certificate is missing from DSM, but the existing production certificate is still safely stored by SadlerACME. <b>Re-deploy Existing</b> restores that certificate without contacting Let's Encrypt. If DSM must create a new certificate entry, the current <b>Set as default only when creating a new DSM certificate</b> setting is used.</div>
EOF2
if [ "$WORKER_LAST" = "Not detected yet" ]; then
cat <<EOF2
<div id="settingsWorkerNotice" class="note"><b>Background processing is not ready.</b> Use Setup Wizard or configure Automation before requesting certificate actions.</div><details class="action-help"><summary>Background processing and certificate actions</summary><p>Setup Wizard starts the processing it needs. For manual setup, open Automation, install or update the bootstrap task and run it once. Check the task and queue watcher before requesting an action. Staging uses separate test storage; Issue / Apply can contact the certificate authority, and Renew Early requires confirmation.</p></details>
EOF2
fi
cat <<EOF2
  </div>
</div>

<div id="tab-automation" class="tabpane">
  <div class="page-heading"><h1>Automation</h1><p>Keep background processing available after a restart and choose whether to check for renewal automatically.</p></div>
  <div class="automation-grid">
    <div class="card"><h2>Background processing</h2><div class="kvgrid">
        <div class="k">Preferred task</div><div id="schedStatus" class="v">$(html_escape "$SCHED_STATUS")</div>
        <div class="k">Details</div><div id="schedDetail" class="v">$(html_escape "$SCHED_DETAIL")</div>
        <div class="k">Queue watcher</div><div id="schedQueueState" class="v">$(html_escape "$QUEUE_STATE")</div>
        <div class="k">Renewal timer</div><div id="schedTimerState" class="v">$(html_escape "$TIMER_STATE")</div>
        <div class="k">Last checked</div><div id="schedLast" class="v">$(html_escape "$SCHED_LAST")</div>
      </div><div class="actions">
        <form id="schedulerStatusForm" class="actionForm" method="post"><input type="hidden" name="csrf" value="$(html_escape "$CSRF")"><input type="hidden" name="action" value="scheduler-status"><button id="schedulerStatusBtn" class="btn secondary" type="submit"><span class="spinner" aria-hidden="true"></span><span class="label">Check Scheduler Status</span></button></form>
        <button id="installSchedulerBtn" class="btn" type="button">Install / Update Task</button>
      </div>
      <div id="schedulerInstallResult" class="inlineStatus show $(html_escape "$SCHED_BANNER_CLASS")">$(html_escape "$SCHED_BANNER_TEXT")</div>
      <div class="muted scheduler-explanation">Status checking is read-only. <b>Install / Update Task</b> uses the administrator session already signed in to DSM and asks only for a one-time password confirmation before creating, updating or removing the root boot-up task. Download a recovery backup from <b>Backup &amp; Restore</b> and prepare removal from <b>Uninstall</b>. Package Center removes SadlerACME data; DSM-installed certificates remain. The password is not posted to SadlerACME's CGI backend or saved.</div></div>
    <div class="card"><h2>Automatic renewal</h2><div class="check"><input type="checkbox" id="auto" value="1"$([ "$AUTO" = "1" ] && printf ' checked')><label for="auto">Check for renewal every 6 hours</label></div><div class="card-footer"><button class="btn secondary" id="saveAutoBtn" type="button">Save renewal setting</button><span id="autoSaveMessage" class="muted small"></span></div></div>
<div class="card"><h2>Boot-up task configuration</h2><div class="kvgrid">
        <div class="k">Expected trigger</div><div class="v">Boot-up</div>
        <div class="k">Expected user</div><div class="v">root</div>
        <div class="k">Expected command</div><div class="v small"><code class="command">/bin/systemctl start pkg-sadleracme-bootstrap.service</code></div>
      </div><div class="divider"></div><details><summary class="disclosure-heading">Show manual setup instructions</summary><div class="note manual-help-note">
        Control Panel → Task Scheduler → Create → Triggered Task → User-defined script<br><br>
        <b>Task:</b> SadlerACME Bootstrap<br><b>User:</b> root<br><b>Event:</b> Boot-up<br><b>Command:</b><br><code class="command">/bin/systemctl start pkg-sadleracme-bootstrap.service</code><br><br>
        After creating it, run the task once or reboot, then click <b>Check Scheduler Status</b>. This manual method remains available if you prefer not to enter DSM administrator credentials into SadlerACME.
      </div></details></div>
  </div>
</div>

<div id="schedulerInstallModal" class="modalback" aria-hidden="true">
  <div class="modalbox">
    <h2>Manage SadlerACME bootstrap task</h2>
    <div class="muted">This uses the DSM administrator session that is already signed in to the DSM desktop. Enter that account's password once to authorize creation of the root boot-up task. The password is sent directly to DSM's WebAPI in your browser and is not posted to the SadlerACME CGI backend or saved.</div>
    <div class="note">Migrating an older task? Choose <b>Update existing task</b> to replace its old command.</div>
    <form id="schedulerInstallForm">
      <input type="hidden" name="csrf" value="$(html_escape "$CSRF")">
      <div class="field"><label>Task action</label><select id="schedulerMode"><option value="create">Create task (new installation)</option><option value="set">Update existing task (upgrade / repair)</option></select></div>
      <div class="field"><label>DSM administrator password</label><input id="schedAdminPass" type="password" autocomplete="current-password" required></div>
      <div class="muted small approval-help">Two-factor authentication is already covered by your current DSM desktop session, so no OTP is requested here.</div>
      <div id="schedulerModalResult" class="inlineStatus"></div>
      <div class="modalactions"><button id="schedulerCancel" class="btn secondary" type="button">Cancel</button><button id="schedulerInstallSubmit" class="btn" type="submit">Continue</button></div>
    </form>
  </div>
</div>

<div id="tab-backup" class="tabpane"></div>
<div id="tab-uninstall" class="tabpane"></div>

<div id="tab-logs" class="tabpane logs-page">
  <div class="page-heading"><h1>Logs</h1><p>Review certificate operations and background processing. Filter the display or copy the visible log.</p></div>
  <div class="card logs-card"><div class="logToolbar"><input id="logFilter" aria-label="Filter log text" type="text" placeholder="Filter log text"><button id="copyLog" class="btn secondary" type="button">Copy</button><button id="pauseLog" class="btn secondary" type="button">Pause live</button><button id="clearLog" class="btn secondary" type="button">Clear log</button><div class="spacer"></div><span id="logState" class="muted small">Live</span></div><div id="fullLog" class="log" tabindex="0" role="region" aria-label="Log output">$(html_escape "$LOGTAIL")</div></div>
</div>
<div id="tab-about" class="tabpane">
<div class="page-heading"><h1>Help &amp; About</h1><p>Setup instructions, recovery guidance and project information.</p></div>
<div class="section-grid">
<div class="card"><h2>Guides</h2>
  <p><a href="QUICKSTART.html" target="_blank" rel="noopener noreferrer">QuickStart</a><br><span class="muted">The essential steps to set up a certificate and automatic renewal.</span></p>
  <p><a href="WORKFLOW.html" target="_blank" rel="noopener noreferrer">Setup and everyday use</a><br><span class="muted">Guided setup, certificate actions, backup and restore.</span></p>
  <p><a href="RECOVERY.html" target="_blank" rel="noopener noreferrer">Recovery and manual removal</a><br><span class="muted">Troubleshooting and the SSH removal procedure when the app cannot complete preparation.</span></p>
</div>
<div class="card">
  <h2>About SadlerACME</h2>
  <p>Synology DNS-01 certificate manager · v$VERSION</p>
  <p><b>SadlerACME — original project by Shane Sadler</b><br>Copyright &copy; 2026 Shane Sadler.</p>
  <p>You may redistribute and modify SadlerACME under the GNU General Public License, version 3 only. Distributed without warranty; see the licence below for details.</p>
  <p>Includes unmodified acme.sh 3.1.5 and its Cloudflare DNS plugin by the acme.sh project and contributors, under their supplied GPLv3 licence. Their original notices are retained.</p>
  <details><summary class="disclosure-heading">Read the full GPLv3 licence</summary>
    <pre class="licence-text">$(html_escape "$(cat "$BASE/target/ui/LICENSE.txt" 2>/dev/null || printf '%s' 'The bundled licence text is unavailable. The GNU GPL version 3 text is available at https://www.gnu.org/licenses/gpl-3.0.html')")</pre>
  </details>
</div>
</div>
</div>
</main></div></div>
<script>
(function(){
  // Keep the DSM token on every request, including status polls and actions.
  // Native Settings submissions retain the current document's query string.
  var dsmToken = new URLSearchParams(window.location.search).get('SynoToken') || '';
  function apiUrl(query){
    var params = new URLSearchParams(query || '');
    if(dsmToken)params.set('SynoToken',dsmToken);
    var encoded = params.toString();
    return '/webman/3rdparty/sadleracme/index.cgi' + (encoded ? '?' + encoded : '');
  }
  var rawLog = document.getElementById('fullLog').textContent || '';
  var paused=false, timer=null, lastState='$(html_escape "$STATE")';

  function setText(id,v){var e=document.getElementById(id); if(e)e.textContent=(v===undefined||v===null||v==='')?'—':v;}
  function setClass(id,cls){var e=document.getElementById(id); if(e)e.className='v '+cls;}
  function prettyNext(epoch,enabled,timerState,stale,serverEpoch){
    if(enabled!=='1')return 'Disabled';
    if(timerState==='inactive'||timerState==='failed')return 'Timer '+timerState;
    if(timerState!=='active')return 'Waiting for timer status';
    var n=/^[0-9]{1,10}$/.test(String(epoch||''))?Number(epoch):0;
    var now=Number(serverEpoch)||Date.now()/1000;
    if(stale==='yes'||(n>0&&n<=now))return 'Status needs refresh';
    return n>0?new Date(n*1000).toLocaleString():'Waiting for timer status';
  }
  var lastStatus=null, refreshPending=null, refreshProblem='', lastRefreshRequest=0;
  // Only a pristine, idle, running installation gets onboarding language.
  // A rejected request, stopped package or previously configured failure stays visible.
  function initialSetupPending(d){
    return d.setup_required==='yes' && d.package_running==='yes' && d.state==='idle' &&
      !d.active_job && d.uninstall_ready!=='yes' && d.wizard_apply_pending!=='yes' &&
      (d.scheduler_status==='Not checked'||d.scheduler_status==='Missing') &&
      (d.worker_last==='Not detected yet'||!d.worker_last);
  }
  function statusIsStale(d){return d.dsm_freshness==='stale';}
  function renderFreshness(d){
    if(!d)return;
    var freshSetup=initialSetupPending(d);
    if(refreshPending&&Date.now()-refreshPending.started>90000){
      refreshPending=null;lastRefreshRequest=Date.now();refreshProblem='Status refresh has not completed. Check background processing in Automation, then try Refresh status again.';
    }
    var stale=statusIsStale(d), nextStale=d.auto_renew==='1'&&d.next_auto_stale==='yes';
    var waiting=refreshPending!==null;
    var text='Live status updates automatically.';
    if(refreshProblem)text=refreshProblem;
    else if(freshSetup)text='Use Setup Wizard to get started, or enter Certificate settings manually.';
    else if(waiting)text='Refreshing status… The last operation result remains above.';
    else if(stale||nextStale)text='Status needs refresh. The last operation result remains above.';
    else if(d.dsm_freshness==='unverified')text='DSM status has not been checked yet.';
    setText('statusFreshness',text);
    var button=document.getElementById('statusRefreshBtn');
    if(button){button.disabled=freshSetup||waiting||d.state==='running'||d.state==='queued';button.textContent=waiting?'Refreshing…':'Refresh status';}
    if(freshSetup){setText('autoRenew','Not active — setup required');setText('nextAuto','Setup required');}
    if(stale&&!freshSetup){
      var label=waiting?'Refreshing…':'Status needs refresh';
      setText('dsmMatch',label);setClass('dsmMatch','muted');
      setText('dsmDefault',label);setText('dsmDefaultState',label);setClass('dsmDefaultState','muted');
    }
    if(nextStale&&!freshSetup)setText('nextAuto',waiting?'Refreshing…':'Status needs refresh');
  }
  function requestStatusRefresh(d){
    if(refreshPending||initialSetupPending(d))return Promise.resolve();
    lastRefreshRequest=Date.now();refreshProblem='';
    var pending={started:Date.now(),id:''};refreshPending=pending;
    renderFreshness(d);
    var q=new URLSearchParams({csrf:'$(html_escape "$CSRF")',action:'refresh'});
    return fetch(apiUrl(),{method:'POST',body:q,credentials:'same-origin'}).then(checkActionResponse).then(function(response){
      if(!response.job_id)throw new Error('The worker did not identify the refresh request');
      if(refreshPending===pending)pending.id=response.job_id;
    }).catch(function(e){
      if(refreshPending!==pending)return;
      refreshPending=null;refreshProblem='Status refresh failed: '+(e.message||'request failed')+'. Check Automation and try Refresh status again.';
      renderFreshness(lastStatus||d);
    });
  }
  function checkRefreshReceipt(){
    var pending=refreshPending;
    if(!pending||!pending.id)return Promise.resolve();
    return fetch(apiUrl(new URLSearchParams({api:'job',id:pending.id})),{cache:'no-store',credentials:'same-origin'}).then(function(r){
      if(!r.ok)throw new Error('HTTP '+r.status);return r.json();
    }).then(function(receipt){
      if(refreshPending!==pending||receipt.job_id!==pending.id)return;
      if(receipt.result==='completed'){refreshPending=null;refreshProblem='';}
      else if(receipt.result==='failed'||receipt.result==='interrupted'){
        refreshPending=null;refreshProblem='Status refresh failed. Check Logs and background processing in Automation, then try Refresh status again.';
      }
    }).catch(function(){
      if(refreshPending===pending)refreshProblem='Unable to confirm status refresh. Checking again automatically; check your DSM session if this continues.';
    });
  }
  function badgeClass(s){return s==='success'?'ok':s==='running'?'run':s==='queued'?'queue':s==='error'?'bad':'idle';}
  function renderLog(){var box=document.getElementById('fullLog'); if(!box)return; var filter=(document.getElementById('logFilter').value||'').toLowerCase(); var nearBottom=(box.scrollHeight-box.scrollTop-box.clientHeight)<55; var shown=rawLog; if(filter){shown=rawLog.split(/\n/).filter(function(x){return x.toLowerCase().indexOf(filter)>=0;}).join('\n');} box.textContent=shown; if(nearBottom)box.scrollTop=box.scrollHeight;}
  function updateSchedulerBanner(status){
    var box=document.getElementById('schedulerInstallResult'); if(!box)return;
    var text='Scheduler status has not been checked yet. Use Check Scheduler Status to inspect the DSM boot-up task.';
    var kind='';
    if(status==='Installed and enabled'){kind='ok';text='SadlerACME Bootstrap is installed, enabled and ready.';}
    else if(status==='Installed but disabled'){kind='warn';text='SadlerACME Bootstrap is installed but disabled. To keep SadlerACME automatic renewal and worker services available after a restart, open DSM Task Scheduler and enable “SadlerACME Bootstrap”.';}
    else if(status==='Missing'){kind='warn';text='SadlerACME Bootstrap is not installed. Use Install Scheduler Task to restore automatic startup.';}
    else if(status==='Incorrect configuration'){kind='err';text='SadlerACME Bootstrap exists but does not match the expected root boot-up configuration. Correct or remove the task in DSM Task Scheduler, then check the scheduler status again.';}
    else if(status==='Detected — details unavailable'){kind='warn';text='SadlerACME Bootstrap was detected, but DSM did not provide enough detail to verify its configuration.';}
    else if(status==='Unable to inspect'){kind='err';text='SadlerACME could not inspect DSM Task Scheduler. Check the scheduler status again or use the manual setup instructions.';}
    box.textContent=text;box.className='inlineStatus show'+(kind?' '+kind:'');
  }
  function applyStatus(d){
    lastStatus=d;
    if(window.SadlerWorkflow && window.SadlerWorkflow.acceptStatus) window.SadlerWorkflow.acceptStatus(d);
    lastState=d.state||'idle';
    document.querySelectorAll('.actionForm:not(#schedulerStatusForm) button').forEach(function(b){b.disabled=(lastState==='running'||lastState==='queued');});
    var b=document.getElementById('stateBadge'); if(b){b.textContent=lastState;b.className='badge '+badgeClass(lastState);}
    setText('statusMessage',d.message); setText('lastAction',d.last_action); setText('lastRun',d.last_run); setText('workerLast',d.worker_last);
    setText('certIssuer',d.issuer); setText('certFrom',d.not_before); setText('certExpires',d.not_after); setText('certDays',(d.days&&d.days!=='—')?d.days+' days':'—'); setText('certSans',d.sans); setText('certFingerprint',d.fingerprint);
    setText('dsmId',d.dsm_id); setText('dsmDefault',d.dsm_default); setText('deployMethod',d.deployment_method); setText('mailplusReload',d.mailplus_reload); setText('lastDeploy',d.last_deploy); setText('lastVerified',d.last_verified); setText('lastIssue',d.last_issue); setText('lastRenewal',d.last_renewal); setText('lastStaging',d.last_staging);
    setText('autoRenew',d.auto_renew_text);setText('nextAuto',prettyNext(d.next_auto,d.auto_renew,d.timer_state,d.next_auto_stale,d.server_epoch));
    setText('schedulerSummary',d.scheduler_status); setText('queueState',d.queue_state); setText('timerState',d.timer_state); setText('schedStatus',d.scheduler_status); setText('schedDetail',d.scheduler_detail); setText('schedLast',d.scheduler_last); setText('schedQueueState',d.queue_state); setText('schedTimerState',d.timer_state);
    var sib=document.getElementById('installSchedulerBtn'); if(sib)sib.disabled=false;
    updateSchedulerBanner(d.scheduler_status);
    if(d.dsm_match==='yes'){setText('dsmMatch','Verified — certificate matches');setClass('dsmMatch','good');}else if(d.dsm_match==='no'){setText('dsmMatch','Mismatch — certificate differs');setClass('dsmMatch','badtext');}else if(d.dsm_match==='not found'){setText('dsmMatch','Certificate not found in DSM');setClass('dsmMatch','badtext');}else{setText('dsmMatch','Not yet verified');setClass('dsmMatch','muted');}
    var redeployReady=(d.dsm_match==='not found'&&d.local_cert_available==='yes');
    var rf=document.getElementById('redeployForm');if(rf)rf.style.display=redeployReady?'':'none';
    var rn=document.getElementById('redeployNotice');if(rn)rn.className='inlineStatus warn'+(redeployReady?' show':'');
    if(d.dsm_default_raw==='true'||d.dsm_default_raw==='1'||d.dsm_default_raw==='yes'||d.dsm_default_raw==='Yes'){setText('dsmDefaultState','Default certificate');setClass('dsmDefaultState','good');}else if(d.dsm_default_raw==='false'||d.dsm_default_raw==='0'||d.dsm_default_raw==='no'||d.dsm_default_raw==='No'){setText('dsmDefaultState','Not the DSM default');setClass('dsmDefaultState','muted');}else{setText('dsmDefaultState','Not yet determined');setClass('dsmDefaultState','muted');}
    var workerNotice=document.getElementById('settingsWorkerNotice');
    if(workerNotice)workerNotice.hidden=d.worker_available==='yes';
    renderFreshness(d);
    if(!paused && typeof d.log==='string'){rawLog=d.log;renderLog();}
  }
  function checkActionResponse(r){return r.text().then(function(t){var d;try{d=JSON.parse(t);}catch(e){throw new Error(t||('HTTP '+r.status));}if(!r.ok||!d.ok)throw new Error(d.message||('HTTP '+r.status));return d;});}
  function showError(e){setText('statusMessage',e.message||'Request failed');var b=document.getElementById('stateBadge');b.textContent='error';b.className='badge bad';}
  function schedule(){clearTimeout(timer); if(document.hidden)return; var delay=(lastState==='running'||lastState==='queued')?2000:10000; timer=setTimeout(poll,delay);}
  function fetchStatusOnce(){return checkRefreshReceipt().then(function(){return fetch(apiUrl('api=status'),{cache:'no-store',credentials:'same-origin'});}).then(function(r){
    if(!r.ok)throw new Error('HTTP '+r.status);return r.json();
  }).then(function(d){
    applyStatus(d);
    if(!initialSetupPending(d)&&d.state!=='running'&&d.state!=='queued'&&!refreshPending&&Date.now()-lastRefreshRequest>60000&&
       ((Number(d.server_epoch)||Date.now()/1000)-Number(d.checked_epoch||0)>60||d.next_auto_stale==='yes')){
      requestStatusRefresh(d);
    }
    document.getElementById('logState').textContent=paused?'Paused':'Live';return d;
  });}
  function poll(){return fetchStatusOnce().catch(function(){
    document.getElementById('logState').textContent='Refresh failed';
    setText('statusFreshness','Cannot update status. Check your DSM session or connection, then try Refresh status again.');
    var button=document.getElementById('statusRefreshBtn');if(button){button.disabled=false;button.textContent='Refresh status';}
  }).finally(schedule);}
  document.getElementById('statusRefreshBtn').addEventListener('click',function(){
    if(lastStatus)requestStatusRefresh(lastStatus).then(function(){return poll();});else poll();
  });
  // Wide windows show a horizontal navigation bar. Narrow windows use the compact menu button.
  var menuToggle=document.getElementById('menuToggle'),navigation=document.getElementById('appNavigation'),appWrap=document.querySelector('.wrap');
  function setCompactMenu(open){
    menuToggle.setAttribute('aria-expanded',open?'true':'false');
    menuToggle.setAttribute('aria-label',open?'Hide navigation menu':'Show navigation menu');
    appWrap.classList.toggle('menu-open',open);
  }
  menuToggle.addEventListener('click',function(){setCompactMenu(menuToggle.getAttribute('aria-expanded')!=='true');});
  window.addEventListener('resize',function(){if(window.innerWidth>820)setCompactMenu(false);});
  var pageScrolls={};
  document.querySelectorAll('.tabbtn').forEach(function(btn){btn.addEventListener('click',function(){
    var target=document.getElementById('tab-'+btn.getAttribute('data-tab'));if(!target)return;
    var main=document.getElementById('mainContent'),previous=document.querySelector('.tabbtn.active');
    if(main&&previous)pageScrolls[previous.getAttribute('data-tab')]=main.scrollTop;
    document.querySelectorAll('.tabbtn').forEach(function(b){b.classList.remove('active');b.removeAttribute('aria-current');});
    document.querySelectorAll('.tabpane').forEach(function(p){p.classList.remove('active');});
    btn.classList.add('active');btn.setAttribute('aria-current','page');target.classList.add('active');
    if(typeof window.innerWidth==='number'&&window.innerWidth<=820)setCompactMenu(false);
    try{sessionStorage.setItem('sadleracme.tab',btn.getAttribute('data-tab'));}catch(e){}
    if(main)main.scrollTop=pageScrolls[btn.getAttribute('data-tab')]||0;
    if(btn.getAttribute('data-tab')==='logs'){renderLog();var l=document.getElementById('fullLog');l.scrollTop=l.scrollHeight;}
  });});
  document.getElementById('viewLogBtn').addEventListener('click',function(){document.querySelector('.tabbtn[data-tab="logs"]').click();});
  document.querySelectorAll('.actionForm').forEach(function(form){form.addEventListener('submit',function(ev){if(form.id==='schedulerStatusForm')return;ev.preventDefault();if(form.classList.contains('forceForm')&&!confirm('Force an early production renewal now? This contacts Let\'s Encrypt and may count toward rate limits. Continue?'))return;if(form.classList.contains('redeployForm')&&!confirm('Re-deploy the existing SadlerACME production certificate to DSM? This does not request a new certificate from Let\'s Encrypt. Continue?'))return;var buttons=form.querySelectorAll('button');buttons.forEach(function(x){x.disabled=true;});fetch(apiUrl(),{method:'POST',body:new URLSearchParams(new FormData(form)),credentials:'same-origin'}).then(checkActionResponse).then(function(){lastState='queued';return poll();}).catch(showError).finally(function(){buttons.forEach(function(x){x.disabled=(lastState==='running'||lastState==='queued');});});});});

  var schedulerStatusForm=document.getElementById('schedulerStatusForm');
  if(schedulerStatusForm){schedulerStatusForm.addEventListener('submit',function(ev){
    ev.preventDefault();
    var btn=document.getElementById('schedulerStatusBtn'),label=btn.querySelector('.label');
    var before=(document.getElementById('schedLast').textContent||'').trim();
    btn.disabled=true;btn.classList.add('checking');label.textContent='Checking…';
    fetch(apiUrl(),{method:'POST',body:new URLSearchParams(new FormData(schedulerStatusForm)),credentials:'same-origin'}).then(checkActionResponse).then(function(){
      lastState='queued';
      var started=Date.now();
      function waitForRefresh(){
        fetchStatusOnce().then(function(d){
          var now=(d.scheduler_last||'').trim();
          if(now && now!==before){btn.disabled=false;btn.classList.remove('checking');label.textContent='Check Scheduler Status';schedule();return;}
          if(Date.now()-started>45000){btn.disabled=false;btn.classList.remove('checking');label.textContent='Check Scheduler Status';schedule();return;}
          setTimeout(waitForRefresh,900);
        }).catch(function(){if(Date.now()-started>45000){btn.disabled=false;btn.classList.remove('checking');label.textContent='Check Scheduler Status';schedule();}else{setTimeout(waitForRefresh,1200);}});
      }
      waitForRefresh();
    }).catch(function(e){showError(e);btn.disabled=false;btn.classList.remove('checking');label.textContent='Check Scheduler Status';});
  });}
  var installBtn=document.getElementById('installSchedulerBtn');
  var installModal=document.getElementById('schedulerInstallModal');
  var installForm=document.getElementById('schedulerInstallForm');
  var modalResult=document.getElementById('schedulerModalResult');
  var pageResult=document.getElementById('schedulerInstallResult');
  var pendingSchedulerRequest='';
  var schedulerRequestTimer=null;

  function closeInstallModal(){
    installModal.classList.remove('open');
    installModal.setAttribute('aria-hidden','true');
    document.getElementById('schedAdminPass').value='';
  }

  function queueSchedulerRefresh(){
    var fd=new URLSearchParams();
    fd.set('csrf',installForm.querySelector('[name=csrf]').value);
    fd.set('action',document.getElementById('schedulerMode').value==='delete'?'prepare-uninstall':'scheduler-status');
    return fetch(apiUrl(),{method:'POST',body:fd,credentials:'same-origin',cache:'no-store'}).then(checkActionResponse);
  }

  window.addEventListener('message',function(e){
    var r=e.data||{};
    if(e.origin!==window.location.origin||e.source!==window.parent||r.type!=='sadleracme.scheduler.result'||!pendingSchedulerRequest||r.requestId!==pendingSchedulerRequest)return;
    clearTimeout(schedulerRequestTimer);schedulerRequestTimer=null;pendingSchedulerRequest='';
    var submit=document.getElementById('schedulerInstallSubmit');submit.disabled=false;
    modalResult.textContent=r.message||'No response';modalResult.className='inlineStatus show '+(r.ok?'ok':'err');
    if(r.ok){
      pageResult.textContent=r.message;pageResult.className='inlineStatus show ok';
      queueSchedulerRefresh().catch(function(e){modalResult.textContent=e.message;modalResult.className='inlineStatus show err';}).finally(function(){setTimeout(poll,700);});
      setTimeout(function(){closeInstallModal();poll();},1400);
    }
  });

  if(installBtn){installBtn.addEventListener('click',function(){
    modalResult.className='inlineStatus';modalResult.textContent='';
    document.getElementById('schedulerMode').value=(document.getElementById('schedStatus').textContent==='Missing'||document.getElementById('schedStatus').textContent==='Not checked')?'create':'set';
    installModal.classList.add('open');installModal.setAttribute('aria-hidden','false');
    setTimeout(function(){document.getElementById('schedAdminPass').focus();},0);
  });}
  document.getElementById('schedulerCancel').addEventListener('click',closeInstallModal);
  installModal.addEventListener('click',function(e){if(e.target===installModal)closeInstallModal();});
  installForm.addEventListener('submit',function(e){
    e.preventDefault();
    var pass=document.getElementById('schedAdminPass').value||'';
    if(!pass)return;
    var submit=document.getElementById('schedulerInstallSubmit');submit.disabled=true;
    modalResult.className='inlineStatus show';modalResult.textContent='Asking DSM to authorize the selected task change…';

    if(window.parent===window){
      document.getElementById('schedAdminPass').value='';submit.disabled=false;
      modalResult.textContent='Automatic installation requires SadlerACME to be opened from the DSM desktop so it can use your existing DSM administrator session. Reopen the app from DSM, or use the manual setup instructions.';
      modalResult.className='inlineStatus show err';
      return;
    }

    pendingSchedulerRequest='sadler-'+Date.now()+'-'+Math.random().toString(36).slice(2);
    window.parent.postMessage({type:'sadleracme.scheduler.install',requestId:pendingSchedulerRequest,password:pass,mode:document.getElementById('schedulerMode').value},window.location.origin);
    pass='';document.getElementById('schedAdminPass').value='';

    clearTimeout(schedulerRequestTimer);
    schedulerRequestTimer=setTimeout(function(){
      if(!pendingSchedulerRequest)return;
      pendingSchedulerRequest='';submit.disabled=false;
      modalResult.textContent='DSM did not return a scheduler-install result. Close SadlerACME, reopen it from the DSM desktop and try again.';
      modalResult.className='inlineStatus show err';
    },45000);
  });

  document.getElementById('logFilter').addEventListener('input',renderLog);
  document.getElementById('copyLog').addEventListener('click',function(){if(navigator.clipboard)navigator.clipboard.writeText(document.getElementById('fullLog').textContent||'');});
  document.getElementById('pauseLog').addEventListener('click',function(){paused=!paused;this.textContent=paused?'Resume live':'Pause live';document.getElementById('fullLog').classList.toggle('paused',paused);document.getElementById('logState').textContent=paused?'Paused':'Live';if(!paused)poll();});
  document.getElementById('clearLog').addEventListener('click',function(){
    if(!confirm('Clear the SadlerACME log? This cannot be undone.'))return;
    var btn=this,oldText=btn.textContent,oldRun=(document.getElementById('lastRun').textContent||'').trim();
    btn.disabled=true;btn.textContent='Clearing…';document.getElementById('logState').textContent='Clearing…';
    var fd=new URLSearchParams();fd.set('csrf','$(html_escape "$CSRF")');fd.set('action','clear-log');
    fetch(apiUrl(),{method:'POST',body:fd,credentials:'same-origin'}).then(checkActionResponse).then(function(){
      lastState='queued';var started=Date.now();
      function waitForClear(){fetchStatusOnce().then(function(d){
        if(d.state!=='queued' && ((d.last_run||'').trim()!==oldRun || Date.now()-started>2500)){
          rawLog=typeof d.log==='string'?d.log:'';renderLog();btn.disabled=false;btn.textContent=oldText;document.getElementById('logState').textContent=paused?'Paused':'Live';schedule();return;
        }
        if(Date.now()-started>30000){btn.disabled=false;btn.textContent=oldText;document.getElementById('logState').textContent='Clear timed out';schedule();return;}
        setTimeout(waitForClear,800);
      }).catch(function(){if(Date.now()-started>30000){btn.disabled=false;btn.textContent=oldText;document.getElementById('logState').textContent='Clear failed';schedule();}else{setTimeout(waitForClear,1100);}});}
      waitForClear();
    }).catch(function(e){showError(e);btn.disabled=false;btn.textContent=oldText;document.getElementById('logState').textContent='Clear failed';});
  });
  document.addEventListener('visibilitychange',function(){if(document.hidden){clearTimeout(timer);}else{poll();}});
  var next=document.getElementById('nextAuto');if(next)next.textContent=prettyNext(next.getAttribute('data-epoch'),next.getAttribute('data-enabled'),next.getAttribute('data-timer'),next.getAttribute('data-stale'),next.getAttribute('data-server-epoch'));
  var savedTab='';try{savedTab=sessionStorage.getItem('sadleracme.tab')||'';}catch(e){}
  document.querySelectorAll('.tabbtn').forEach(function(button){if(button.getAttribute('data-tab')===savedTab)button.click();});
  poll();
})();
</script>
<script>
window.SadlerWorkflowConfig={csrf:$(printf '%s' "$CSRF" | "$JQ" -Rs .),recoveryUrl:'RECOVERY.html'};
(function(){
  var b=document.getElementById('saveAutoBtn'),c=document.getElementById('auto'),m=document.getElementById('autoSaveMessage');
  function url(api){var u=new URL(window.location.href);u.searchParams.set('api',api);return u.toString();}
  b.addEventListener('click',async function(){b.disabled=true;m.textContent='Saving…';try{
    var r=await fetch(url('settings'),{credentials:'same-origin',cache:'no-store'});var d=await r.json();if(!r.ok||!d.ok)throw Error(d.message||'Unable to read settings');
    var u=new URL(window.location.href);u.searchParams.delete('api');
    r=await fetch(u.toString(),{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'save-auto',csrf:window.SadlerWorkflowConfig.csrf,expected_settings_hash:d.settings_hash,auto_renew:c.checked?'1':'0'})});d=await r.json();if(!r.ok||!d.ok)throw Error(d.message||'Unable to save renewal setting');
    document.getElementById('settingsAuto').value=c.checked?'1':'0';m.textContent=d.message;
  }catch(e){m.textContent=e.message;}finally{b.disabled=false;}});
})();
</script><script src="workflow.js?v=$VERSION"></script></body></html>
EOF2
