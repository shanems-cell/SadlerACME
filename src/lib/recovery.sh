# Recovery documents are data, not archives or executable ACME configuration.
# This file is assembled into the verified worker; it is never sourced from
# the installed, package-writable target by a privileged service.

recovery_valid_id() {
  case "$1" in ''|*[!0-9a-f-]*) return 1;; esac
  [ "${#1}" -le 80 ]
}

recovery_find_fingerprint_match() {
  # Called only after the saved DSM ID and exact description found no entry.
  # The inventory is supplied by the caller's read-only DSM list operation.
  # This recovers an existing slot when settings changed its description but
  # the local replacement path preserved DSM's original description.
  [ -s "$LIVE/cert.pem" ] || return 0
  rf_fingerprint=$(cert_fp_normalized "$LIVE/cert.pem")
  case "$rf_fingerprint" in ''|*[!0-9a-f]*) return 0;; esac
  [ "${#rf_fingerprint}" = 64 ] || return 0
  printf '%s' "$1" > "$WORK/fingerprint-inventory.json" || return 1
  "$JQ" -e '.data.certificates|type=="array" and all(.id|type=="string" and length>0 and length<=128 and test("\\A[A-Za-z0-9_-]+\\z")) and ((map(.id)|length)==(map(.id)|unique|length))' "$WORK/fingerprint-inventory.json" >/dev/null || return 1
  "$JQ" -r '.data.certificates[].id' "$WORK/fingerprint-inventory.json" > "$WORK/fingerprint-ids" || return 1
  rf_matches=0; rf_match_id=""
  while IFS= read -r rf_id; do
    # Every identifier was validated before use in this fixed archive path.
    # An unreadable entry prevents proving uniqueness, so fail closed.
    case "$rf_id" in ''|*[!A-Za-z0-9_-]*) return 1;; esac
    rf_candidate=$(cert_fp_normalized "/usr/syno/etc/certificate/_archive/$rf_id/cert.pem")
    case "$rf_candidate" in ''|*[!0-9a-f]*) return 1;; esac
    [ "${#rf_candidate}" = 64 ] || return 1
    if [ "$rf_candidate" = "$rf_fingerprint" ]; then
      rf_matches=$((rf_matches + 1)); rf_match_id="$rf_id"
    fi
  done < "$WORK/fingerprint-ids"
  if [ "$rf_matches" -gt 1 ]; then
    write_public dsm_detail "Several DSM entries contain the recovered certificate. Choose a unique existing certificate description before applying."
    return 2
  fi
  if [ "$rf_matches" = 1 ]; then
    cert=$("$JQ" -c --arg id "$rf_match_id" '.data.certificates[]|select(.id==$id)' "$WORK/fingerprint-inventory.json") || return 1
  fi
  return 0
}

recovery_transfer_directory() {
  [ ! -L "$PROTECTED/transfers" ] || return 1
  mkdir -p "$PROTECTED/transfers" || return 1
  [ "$(stat -c %u "$PROTECTED/transfers")" = 0 ] || return 1
  chgrp "$(stat -Lc %g "$ETC")" "$PROTECTED/transfers" || return 1
  chmod 0750 "$PROTECTED/transfers"
}

recovery_expire_transfers() {
  [ -d "$PROTECTED/transfers" ] && [ ! -L "$PROTECTED/transfers" ] || return 0
  rx_now=$(date +%s) || return 1
  rx_remaining=0
  for rx_file in "$PROTECTED/transfers"/*.json; do
    [ -e "$rx_file" ] || [ -L "$rx_file" ] || continue
    rx_id=${rx_file##*/}; rx_id=${rx_id%.json}
    recovery_valid_id "$rx_id" || continue
    if [ -L "$rx_file" ] || [ ! -f "$rx_file" ]; then rm -f "$rx_file" || return 1; continue; fi
    rx_mtime=$(stat -c %Y "$rx_file") || return 1
    if [ "$rx_mtime" -gt "$rx_now" ] || [ "$((rx_now - rx_mtime))" -ge 900 ]; then
      rm -f "$rx_file" || return 1
    else rx_remaining=1; fi
  done
  rx_published=$(read_status_value backup_download)
  if [ -n "$rx_published" ]; then
    if ! recovery_valid_id "$rx_published" || [ ! -f "$PROTECTED/transfers/$rx_published.json" ]; then
      write_public backup_download "" || return 1
    fi
  fi
  if [ "$rx_remaining" = 0 ]; then
    # DSM's systemd 219 does not support --now. Attempt both operations even
    # if removing the boot-time enablement fails; stopping the timer is safe
    # when this function runs inside its associated expiry service.
    systemctl disable pkg-sadleracme-transfer-expire.timer >/dev/null 2>&1 || true
    systemctl stop pkg-sadleracme-transfer-expire.timer >/dev/null 2>&1 || true
  fi
}

backup_delete() {
  bd_id=$("$JQ" -er '.transfer_id | select(type=="string")' "$WORK/job.json") || fail "Invalid backup download identifier" backup
  recovery_valid_id "$bd_id" || fail "Invalid backup download identifier" backup
  rm -f "$PROTECTED/transfers/$bd_id.json" || fail "Cannot remove temporary recovery download" backup
  [ "$(read_status_value backup_download)" != "$bd_id" ] || write_public backup_download ""
  recovery_expire_transfers
}

recovery_validate_settings() {
  # Empty domains/email are allowed for a settings-only backup of an untouched
  # installation. No unknown fields, control characters, paths or shell hooks.
  "$JQ" -e '
    type=="object" and
    ((keys|sort)==(["email","domains","key_type","cert_desc","default_on_create","auto_renew","dns_sleep"]|sort)) and
    (.email|type=="string" and length<=254 and (.=="" or test("\\A[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}\\z"))) and
    (.domains|type=="array" and length<=100 and (length==(unique|length)) and
      all(type=="string" and length<=253 and test("^(\\*\\.)?([a-z0-9]([a-z0-9-]*[a-z0-9])?\\.)+[a-z]{2,}$"))) and
    (.key_type=="ec-256" or .key_type=="ec-384" or .key_type=="rsa-2048" or .key_type=="rsa-4096") and
    (.cert_desc|type=="string" and length>0 and length<=80 and (explode|all(.>=32 and .!=127))) and
    (.default_on_create=="0" or .default_on_create=="1") and .auto_renew=="0" and
    (.dns_sleep|type=="string" and test("^[0-9]{2,3}$") and (tonumber>=30 and tonumber<=600))
  ' "$1" >/dev/null 2>&1
}

recovery_canonical_pems() (
  rc_source="$1"; rc_dest="$2"
  mkdir -p "$rc_dest" || exit 1
  for rc_name in key.pem cert.pem ca.pem fullchain.pem; do
    [ -f "$rc_source/$rc_name" ] && [ ! -L "$rc_source/$rc_name" ] || exit 1
    [ "$(stat -c %s "$rc_source/$rc_name")" -le 131072 ] || exit 1
  done
  # Parsing and rewriting PEM eliminates comments, unrelated text and hidden
  # configuration fields. Do not export the input verbatim.
  "$OPENSSL" pkey -in "$rc_source/key.pem" -passin pass: -check -noout >/dev/null 2>&1 || exit 1
  "$OPENSSL" pkey -in "$rc_source/key.pem" -passin pass: -out "$rc_dest/key.pem" 2>/dev/null || exit 1
  "$OPENSSL" x509 -in "$rc_source/cert.pem" -out "$rc_dest/cert.pem" 2>/dev/null || exit 1
  "$OPENSSL" crl2pkcs7 -nocrl -certfile "$rc_source/ca.pem" -out "$rc_dest/chain.p7" 2>/dev/null || exit 1
  "$OPENSSL" pkcs7 -in "$rc_dest/chain.p7" -print_certs -out "$rc_dest/chain.text" 2>/dev/null || exit 1
  awk '/^-----BEGIN CERTIFICATE-----$/ {in_pem=1} in_pem {print} /^-----END CERTIFICATE-----$/ {in_pem=0}' "$rc_dest/chain.text" > "$rc_dest/ca.pem"
  rm -f "$rc_dest/chain.p7" "$rc_dest/chain.text"
  [ -s "$rc_dest/ca.pem" ] || exit 1
  cat "$rc_dest/cert.pem" "$rc_dest/ca.pem" > "$rc_dest/fullchain.pem" || exit 1
  # Require the submitted full chain to consist of precisely these certificates.
  "$OPENSSL" crl2pkcs7 -nocrl -certfile "$rc_source/fullchain.pem" -out "$rc_dest/full.p7" 2>/dev/null || exit 1
  "$OPENSSL" pkcs7 -in "$rc_dest/full.p7" -print_certs -out "$rc_dest/full.text" 2>/dev/null || exit 1
  awk '/^-----BEGIN CERTIFICATE-----$/ {in_pem=1} in_pem {print} /^-----END CERTIFICATE-----$/ {in_pem=0}' "$rc_dest/full.text" > "$rc_dest/full.canonical"
  cmp -s "$rc_dest/full.canonical" "$rc_dest/fullchain.pem" || exit 1
  rm -f "$rc_dest/full.p7" "$rc_dest/full.text" "$rc_dest/full.canonical"
  chmod 0600 "$rc_dest/"*.pem
  validate_pair "$rc_dest"
)

recovery_certificate_matches() (
  # This validation intentionally permits expired certificates in backups.
  # Expiry/trust is checked separately before reconstructing a usable profile;
  # restore must still recover data when an administrator missed renewal.
  rm_settings="$1"; rm_certdir="$2"
  rm_kind=$("$JQ" -r .key_type "$rm_settings")
  [ "$(actual_key_type "$rm_certdir/key.pem")" = "$rm_kind" ] || exit 1
  "$OPENSSL" x509 -in "$rm_certdir/cert.pem" -noout -ext subjectAltName 2>/dev/null |
    tr ',' '\n' | sed -n 's/^[[:space:]]*DNS://p' | tr 'A-Z' 'a-z' | sort -u > "$WORK/recovery-actual-sans"
  "$JQ" -r '.domains[]' "$rm_settings" | sort -u > "$WORK/recovery-expected-sans"
  [ -s "$WORK/recovery-expected-sans" ] && cmp -s "$WORK/recovery-actual-sans" "$WORK/recovery-expected-sans"
)

backup_export() {
  be_id=${ACTIVE_JOB%.job}
  recovery_valid_id "$be_id" || fail "Recovery export requires a queued request" backup
  recovery_transfer_directory || fail "Cannot create protected recovery download storage" backup
  recovery_expire_transfers || fail "Cannot expire previous recovery downloads" backup
  mkdir -p "$WORK/export" || fail "Cannot create private recovery workspace" backup
  "$JQ" '{email:(.email//""),domains:(.domains//[]),key_type:(.key_type//"ec-384"),cert_desc:(.cert_desc//"SadlerACME wildcard"),default_on_create:(.default_on_create//"0"),auto_renew:"0",dns_sleep:(.dns_sleep//"60")}' "$CONFIG" > "$WORK/export/settings.json" || fail "Cannot read recovery settings" backup
  recovery_validate_settings "$WORK/export/settings.json" || fail "Settings are not suitable for a recovery backup; correct Settings first" backup
  "$JQ" '{domains,key_type}' "$WORK/export/settings.json" > "$WORK/export/metadata.json" || fail "Cannot encode recovery settings metadata" backup
  printf 'null\n' > "$WORK/export/certificate.json" || fail "Cannot prepare recovery certificate data" backup
  if [ -e "$LIVE" ] || [ -L "$LIVE" ]; then
    recovery_canonical_pems "$LIVE" "$WORK/export/pem" || fail "Stored certificate data is incomplete or invalid; backup was not created" backup
    "$OPENSSL" x509 -in "$WORK/export/pem/cert.pem" -noout -ext subjectAltName > "$WORK/export/certificate-sans" 2>/dev/null || fail "Cannot read certificate domains for recovery backup" backup
    tr ',' '\n' < "$WORK/export/certificate-sans" | sed -n 's/^[[:space:]]*DNS://p' | tr 'A-Z' 'a-z' | sort -u > "$WORK/export/certificate-domains" || fail "Cannot prepare certificate domains for recovery backup" backup
    "$JQ" -Rn --arg key_type "$(actual_key_type "$WORK/export/pem/key.pem")" '[inputs] | {domains:.,key_type:$key_type}' < "$WORK/export/certificate-domains" > "$WORK/export/metadata.json" || fail "Cannot encode recovery certificate metadata" backup
    recovery_certificate_matches "$WORK/export/metadata.json" "$WORK/export/pem" || fail "Stored certificate metadata could not be validated" backup
    # DSM can provide jq 1.5, which does not support --rawfile. Encode each
    # canonical PEM as JSON in this root-private workspace, then load the JSON
    # files with --slurpfile. Private keys never become command arguments.
    for be_name in key cert ca fullchain; do
      "$JQ" -Rs . "$WORK/export/pem/$be_name.pem" > "$WORK/export/$be_name.json" || fail "Cannot encode certificate files for recovery backup" backup
    done
    "$JQ" -n --slurpfile key "$WORK/export/key.json" --slurpfile cert "$WORK/export/cert.json" --slurpfile ca "$WORK/export/ca.json" --slurpfile fullchain "$WORK/export/fullchain.json" '{"key.pem":$key[0],"cert.pem":$cert[0],"ca.pem":$ca[0],"fullchain.pem":$fullchain[0]}' > "$WORK/export/certificate.json" || fail "Cannot combine certificate files for recovery backup" backup
  fi
  printf 'null\n' > "$WORK/export/account.json" || fail "Cannot prepare recovery account data" backup
  be_account="$PROD_CFG/ca/acme-v02.api.letsencrypt.org/directory/account.key"
  if [ -e "$be_account" ] || [ -L "$be_account" ]; then
    [ -f "$be_account" ] && [ ! -L "$be_account" ] && [ "$(stat -c %s "$be_account")" -le 16384 ] || fail "ACME account key is not a valid regular file" backup
    "$OPENSSL" pkey -in "$be_account" -passin pass: -check -noout >/dev/null 2>&1 &&
      "$OPENSSL" pkey -in "$be_account" -passin pass: -out "$WORK/export/account.key" 2>/dev/null || fail "ACME account key could not be validated" backup
    "$JQ" -Rs . "$WORK/export/account.key" > "$WORK/export/account.json" || fail "Cannot encode ACME account key for recovery backup" backup
  fi
  "$JQ" -n --arg created "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" --slurpfile settings "$WORK/export/settings.json" --slurpfile cert "$WORK/export/certificate.json" --slurpfile account "$WORK/export/account.json" --slurpfile metadata "$WORK/export/metadata.json" '{format:"SadlerACME",version:1,created_at:$created,settings:$settings[0],certificate:$cert[0],acme_account_key:$account[0],metadata:$metadata[0]}' > "$WORK/export/recovery.json" || fail "Cannot encode recovery backup" backup
  [ "$(stat -c %s "$WORK/export/recovery.json")" -le 524288 ] || fail "Recovery backup exceeds the supported size" backup
  chmod 0640 "$WORK/export/recovery.json" || fail "Cannot set recovery download permissions" backup
  be_group=$(stat -Lc %g "$ETC") || fail "Cannot identify recovery download group" backup
  chgrp "$be_group" "$WORK/export/recovery.json" || fail "Cannot set recovery download group" backup
  if ! systemctl enable pkg-sadleracme-transfer-expire.timer; then
    recovery_expire_transfers || true
    fail "Temporary backup expiry timer could not be enabled; no download was retained" backup
  fi
  if ! systemctl start pkg-sadleracme-transfer-expire.timer; then
    recovery_expire_transfers || true
    fail "Temporary backup expiry service could not be started; no download was retained" backup
  fi
  if [ "$(systemd_unit_state pkg-sadleracme-transfer-expire.timer)" != active ]; then
    recovery_expire_transfers || true
    fail "Temporary backup expiry timer did not become active; no download was retained" backup
  fi
  mv -f "$WORK/export/recovery.json" "$PROTECTED/transfers/$be_id.json" || fail "Cannot prepare recovery download" backup
  write_public backup_download "$be_id"
  write_status success "Recovery backup is ready to download for 15 minutes. It contains private keys but excludes Cloudflare credentials." backup
}

recovery_validate_document() {
  [ "$(stat -c %s "$1")" -le 524288 ] || return 1
  "$JQ" -e '
    type=="object" and
    ((keys|sort)==(["format","version","created_at","settings","certificate","acme_account_key","metadata"]|sort)) and
    .format=="SadlerACME" and .version==1 and
    (.created_at|type=="string" and test("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")) and
    (.metadata|type=="object" and (keys|sort)==(["domains","key_type"]|sort)) and
    (.metadata.domains|type=="array" and length<=100 and all(type=="string" and length<=253 and test("^(\\*\\.)?([a-z0-9]([a-z0-9-]*[a-z0-9])?\\.)+[a-z]{2,}$"))) and
    (.metadata.key_type=="ec-256" or .metadata.key_type=="ec-384" or .metadata.key_type=="rsa-2048" or .metadata.key_type=="rsa-4096") and
    (if .certificate==null then .metadata.domains==.settings.domains and .metadata.key_type==.settings.key_type else (.metadata.domains|length>0) end) and
    (.acme_account_key==null or (.acme_account_key|type=="string" and length>0 and length<=16384)) and
    (.certificate==null or (.certificate|type=="object" and
      ((keys|sort)==(["key.pem","cert.pem","ca.pem","fullchain.pem"]|sort)) and
      all(.[];type=="string" and length>0 and length<=131072)))
  ' "$1" >/dev/null 2>&1 || return 1
  "$JQ" .settings "$1" > "$WORK/recovery-settings.json" || return 1
  recovery_validate_settings "$WORK/recovery-settings.json"
}

recovery_recover_transaction() {
  # Caller holds configuration.lock. All paths are literal and the journal is
  # root-only; never follow filenames or commands supplied by a recovery file.
  rr_tx="$ROOT_STATE/recovery-transaction"
  [ -e "$rr_tx" ] || return 0
  [ -d "$rr_tx" ] && [ ! -L "$rr_tx" ] && [ "$(stat -c %u "$rr_tx")" = 0 ] || return 1
  if [ -f "$rr_tx/committed" ]; then rm -rf "$rr_tx"; return; fi
  if [ -f "$rr_tx/started" ]; then
    for rr_name in live prod-config prod-certs applied_signature dsm-id last-settings.json migration-v1; do
      if [ -e "$rr_tx/old/$rr_name" ] || [ -L "$rr_tx/old/$rr_name" ]; then
        rm -rf "$ROOT_STATE/$rr_name" || return 1
        mv -T "$rr_tx/old/$rr_name" "$ROOT_STATE/$rr_name" || return 1
      elif [ -f "$rr_tx/absent-$rr_name" ]; then
        rm -rf "$ROOT_STATE/$rr_name" || return 1
      fi
    done
    if [ -f "$rr_tx/settings-present" ]; then
      commit_settings_from_file "$rr_tx/old-settings.json" || return 1
    elif [ -f "$rr_tx/settings-absent" ]; then
      rm -f "$ETC/settings.json" || return 1
    else return 1; fi
  fi
  if [ -f "$rr_tx/new-generation" ]; then
    rr_generation=$(cat "$rr_tx/new-generation")
    case "$rr_generation" in live-gen.*) ;; *) return 1;; esac
    case "$rr_generation" in *[!A-Za-z0-9.-]*) return 1;; esac
    rm -rf "$ROOT_STATE/$rr_generation" || return 1
  fi
  rm -rf "$rr_tx"
}

restore_backup() {
  # Caller has taken configuration.lock and checked expected_settings_hash.
  "$JQ" .backup "$WORK/job.json" > "$WORK/recovery.json" || fail "Cannot decode recovery backup" restore
  recovery_validate_document "$WORK/recovery.json" || fail "Recovery backup format, fields or size are invalid" restore
  "$JQ" -e '.config.cf_token | type=="string" and test("^[A-Za-z0-9_-]{20,256}$")' "$WORK/job.json" >/dev/null || fail "Enter a fresh Cloudflare API token before restoring" restore
  # A secret goes through file/stdin, never a --arg process-list argument.
  "$JQ" --slurpfile settings "$WORK/recovery-settings.json" '$settings[0] + {cf_token:.config.cf_token,auto_renew:"0"}' "$WORK/job.json" > "$WORK/restored-settings.json"
  rb_cert=0
  if "$JQ" -e '.certificate!=null' "$WORK/recovery.json" >/dev/null; then
    rb_cert=1; mkdir -p "$WORK/import-pem"
    for rb_pem in key.pem cert.pem ca.pem fullchain.pem; do
      "$JQ" -jr --arg name "$rb_pem" '.certificate[$name]' "$WORK/recovery.json" > "$WORK/import-pem/$rb_pem"
    done
    "$JQ" .metadata "$WORK/recovery.json" > "$WORK/recovery-metadata.json"
    recovery_canonical_pems "$WORK/import-pem" "$WORK/restore-pem" &&
      recovery_certificate_matches "$WORK/recovery-metadata.json" "$WORK/restore-pem" || fail "Recovery certificate, private key, domains or key type do not match" restore
  fi
  rb_account=0
  if "$JQ" -e '.acme_account_key!=null' "$WORK/recovery.json" >/dev/null; then
    rb_account=1
    "$JQ" -jr .acme_account_key "$WORK/recovery.json" > "$WORK/import-account.key"
    "$OPENSSL" pkey -in "$WORK/import-account.key" -passin pass: -check -noout >/dev/null 2>&1 &&
      "$OPENSSL" pkey -in "$WORK/import-account.key" -passin pass: -out "$WORK/restore-account.key" 2>/dev/null || fail "Recovery ACME account key is invalid or encrypted" restore
  fi
  rb_tx="$ROOT_STATE/recovery-transaction"
  [ ! -e "$rb_tx" ] && [ ! -L "$rb_tx" ] || fail "An earlier restore requires transaction recovery" restore
  mkdir -p "$rb_tx/new/prod-config" "$rb_tx/new/prod-certs" "$rb_tx/old"
  if [ "$rb_cert" = 1 ]; then
    mkdir "$rb_tx/new/live"
    cp "$WORK/restore-pem/"*.pem "$rb_tx/new/live/"
    # Generate a safe profile using the same adoption path as existing installs.
    # No restored shell scripts, account.conf, hooks or arbitrary paths execute.
    (
      CONFIG="$WORK/restored-settings.json"
      ROOT_STATE="$rb_tx/new"; LIVE="$ROOT_STATE/live"
      PROD_CFG="$ROOT_STATE/prod-config"; PROD_CERTS="$ROOT_STATE/prod-certs"
      APPLIED_SIG="$ROOT_STATE/applied_signature"
      KEY_TYPE=$(read_setting key_type); PRIMARY=$("$JQ" -r '.domains[0]' "$CONFIG")
      "$JQ" -r '.domains[]' "$CONFIG" > "$WORK/domains"
      case "$KEY_TYPE" in ec-256|ec-384) ACME_KEY="$KEY_TYPE"; ECC=1;; rsa-2048) ACME_KEY=2048; ECC=0;; rsa-4096) ACME_KEY=4096; ECC=0;; esac
      log() { :; }
      adopt_legacy_profile
      # set -e is suppressed by the surrounding checked subshell. Verify all
      # reconstruction outputs explicitly before committing a usable profile.
      if validate_certificate "$LIVE"; then
        [ -s "$APPLIED_SIG" ] && [ "$(cat "$APPLIED_SIG")" = "$(config_signature)" ] || exit 1
        [ "$ECC" = 1 ] && rp_dir="$PROD_CERTS/${PRIMARY}_ecc" || rp_dir="$PROD_CERTS/$PRIMARY"
        cmp -s "$LIVE/key.pem" "$rp_dir/$PRIMARY.key" &&
          cmp -s "$LIVE/cert.pem" "$rp_dir/$PRIMARY.cer" &&
          cmp -s "$LIVE/ca.pem" "$rp_dir/ca.cer" &&
          cmp -s "$LIVE/fullchain.pem" "$rp_dir/fullchain.cer" &&
          [ -s "$rp_dir/$PRIMARY.conf" ] || exit 1
      fi
    ) || { rm -rf "$rb_tx"; fail "Cannot rebuild the certificate renewal profile" restore; }
  fi
  if [ "$rb_account" = 1 ]; then
    mkdir -p "$rb_tx/new/prod-config/ca/acme-v02.api.letsencrypt.org/directory"
    cp "$WORK/restore-account.key" "$rb_tx/new/prod-config/ca/acme-v02.api.letsencrypt.org/directory/account.key"
  fi
  if [ "$rb_cert" = 1 ]; then
    rb_generation=$(mktemp -d "$ROOT_STATE/live-gen.XXXXXXXX") || { rm -rf "$rb_tx"; fail "Cannot allocate restored certificate generation" restore; }
    printf '%s\n' "${rb_generation##*/}" > "$rb_tx/new-generation"
    cp "$rb_tx/new/live/"*.pem "$rb_generation/" || fail "Cannot copy restored certificate generation" restore
    chmod 0600 "$rb_generation/"*.pem
    rm -rf "$rb_tx/new/live"
    ln -s "${rb_generation##*/}" "$rb_tx/new/live"
  fi
  cp "$WORK/restored-settings.json" "$rb_tx/new/last-settings.json"
  # A deliberate validated restore supersedes historical package storage,
  # including settings-only backups. Commit this with the restored state so a
  # later operation cannot re-import old PEMs; rollback restores the old marker.
  : > "$rb_tx/new/migration-v1"
  # Snapshot the settings and existence map BEFORE any privileged data moves.
  if [ -f "$ETC/settings.json" ] && [ ! -L "$ETC/settings.json" ]; then
    head -c 32769 "$ETC/settings.json" > "$rb_tx/old-settings.json"
    [ "$(stat -c %s "$rb_tx/old-settings.json")" -le 32768 ] && "$JQ" -e 'type=="object"' "$rb_tx/old-settings.json" >/dev/null || { rm -rf "$rb_tx"; fail "Current settings could not be safely preserved before restore" restore; }
    : > "$rb_tx/settings-present"
  else : > "$rb_tx/settings-absent"; fi
  for rb_name in live prod-config prod-certs applied_signature dsm-id last-settings.json migration-v1; do
    if [ ! -e "$ROOT_STATE/$rb_name" ] && [ ! -L "$ROOT_STATE/$rb_name" ]; then : > "$rb_tx/absent-$rb_name"; fi
  done
  : > "$rb_tx/started"
  rb_failed=0
  for rb_name in live prod-config prod-certs applied_signature dsm-id last-settings.json migration-v1; do
    if [ -e "$ROOT_STATE/$rb_name" ] || [ -L "$ROOT_STATE/$rb_name" ]; then
      mv -T "$ROOT_STATE/$rb_name" "$rb_tx/old/$rb_name" || { rb_failed=1; break; }
    fi
    if [ -e "$rb_tx/new/$rb_name" ] || [ -L "$rb_tx/new/$rb_name" ]; then
      mv -T "$rb_tx/new/$rb_name" "$ROOT_STATE/$rb_name" || { rb_failed=1; break; }
    fi
  done
  if [ "$rb_failed" = 0 ] && commit_settings_from_file "$WORK/restored-settings.json"; then
    : > "$rb_tx/committed"
  else
    recovery_recover_transaction || fail "Restore failed and rollback is incomplete; protected recovery transaction retained" restore
    fail "Restore failed; the previous SadlerACME data and settings were restored" restore
  fi
  rm -rf "$rb_tx"
  cp "$WORK/restored-settings.json" "$CONFIG"
  CERT_DESC=$(read_setting cert_desc); KEY_TYPE=$(read_setting key_type)
  CF_TOKEN=$(read_setting cf_token)
  printf '%s\n' "$CF_TOKEN" >> "$ROOT_STATE/log-redactions"
  write_public next_auto_epoch ""
  refresh_cert_metadata
  # Forget the old NAS ID; rediscover only from this NAS's current inventory.
  rb_dsm=ok
  refresh_dsm_metadata || rb_dsm=unknown
  write_public restore_requires_issue no
  if [ "$rb_cert" = 0 ] || [ ! -s "$APPLIED_SIG" ]; then
    write_public restore_requires_issue yes
    rb_message="Recovery data restored; a new valid production certificate is required. Automatic renewal is off."
  else
    rb_message="Recovery data restored without issuing or deploying a certificate. Automatic renewal is off; verify DSM and complete setup."
  fi
  [ "$rb_dsm" = ok ] || rb_message="$rb_message DSM identification failed or is ambiguous; resolve it before applying."
  write_status success "$rb_message" restore
}
