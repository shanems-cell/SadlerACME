# Fixed DSM package-storage scope. Included at build time in the verified
# worker, cleanup monitor and standalone emergency tool; never sourced from
# a package-writable runtime file. No caller-provided arbitrary deletion path.
package_storage_scope() (
  ps_path=$1; ps_kind=$2
  case "$ps_kind" in var) ps_bucket=@appdata;; etc) ps_bucket=@appconf;; *) exit 1;; esac
  case "$ps_path" in
    /volume*/"$ps_bucket"/sadleracme)
      ps_volume=${ps_path%%/"$ps_bucket"/*}
      ps_number=${ps_volume#/volume}
      case "$ps_number" in ''|*[!0-9]*) exit 1;; esac
      ;;
    /usr/local/packages/@appdata/sadleracme) [ "$ps_kind" = var ] || exit 1;;
    /usr/syno/etc/packages/sadleracme) [ "$ps_kind" = etc ] || exit 1;;
    *) exit 1;;
  esac
)
package_storage_parents() (
  # The leaf legitimately belongs to the package account. Its parents must
  # prevent that account from replacing the leaf between validation and rm.
  # The volume itself may be a mount; mounts at/below the leaf are forbidden.
  ps_parent=${1%/*}
  while [ "$ps_parent" != / ]; do
    [ -d "$ps_parent" ] && [ ! -L "$ps_parent" ] &&
      [ "$(stat -c %u "$ps_parent")" = 0 ] &&
      [ -z "$(find "$ps_parent" -maxdepth 0 \( -perm -020 -o -perm -002 \) -print)" ] || exit 1
    ps_parent=${ps_parent%/*}; [ -n "$ps_parent" ] || ps_parent=/
  done
)
package_storage_validate() (
  ps_path=$1; ps_kind=$2
  package_storage_scope "$ps_path" "$ps_kind" && package_storage_parents "$ps_path" || exit 1
  [ ! -L "$ps_path" ] || exit 1
  if [ -e "$ps_path" ]; then
    [ -d "$ps_path" ] || exit 1
    ps_mounts=$(awk -v p="$ps_path" '$5==p || index($5,p "/")==1 {print $5}' /proc/self/mountinfo) || exit 1
    [ -z "$ps_mounts" ] || exit 1
  fi
)
package_storage_capture() (
  ps_lookup=$1; ps_kind=$2; ps_record=$3
  # Only the DSM registration lookup may be a symlink. Validate the resolved
  # physical path and all its ancestors before recording the directory inode.
  ps_path=$(readlink -f "$ps_lookup") || exit 1
  case "$ps_lookup" in
    /var/packages/sadleracme/var) [ "$ps_kind" = var ] || exit 1;;
    /var/packages/sadleracme/etc) [ "$ps_kind" = etc ] || exit 1;;
    *) [ "$ps_lookup" = "$ps_path" ] || exit 1;;
  esac
  package_storage_validate "$ps_path" "$ps_kind" || exit 1
  [ -d "$ps_path" ] || exit 1
  ps_identity=$(stat -c '%d:%i' "$ps_path") || exit 1
  ps_parent_identity=$(stat -c '%d:%i' "${ps_path%/*}") || exit 1
  ps_record_parent=${ps_record%/*}
  [ -d "$ps_record_parent" ] && [ ! -L "$ps_record_parent" ] &&
    [ "$(stat -c %u "$ps_record_parent")" = 0 ] &&
    [ -z "$(find "$ps_record_parent" -maxdepth 0 \( -perm -020 -o -perm -002 \) -print)" ] || exit 1
  ps_tmp=$(mktemp "$ps_record.XXXXXXXX") || exit 1
  trap 'rm -f "$ps_tmp"' EXIT
  printf '%s\n%s\n%s\n' "$ps_path" "$ps_identity" "$ps_parent_identity" > "$ps_tmp" &&
    chmod 0600 "$ps_tmp" && mv -f "$ps_tmp" "$ps_record" || exit 1
)
package_storage_verify() (
  ps_record=$1; ps_kind=$2
  [ -f "$ps_record" ] && [ ! -L "$ps_record" ] &&
    [ "$(stat -c %u "$ps_record")" = 0 ] && [ "$(stat -c %a "$ps_record")" = 600 ] &&
    [ "$(stat -c %s "$ps_record")" -le 512 ] && [ "$(wc -l < "$ps_record")" -eq 3 ] || exit 1
  ps_path=$(sed -n '1p' "$ps_record")
  ps_identity=$(sed -n '2p' "$ps_record")
  case "$ps_identity" in ''|*[!0-9:]*|:*|*:) exit 1;; esac
  ps_device=${ps_identity%%:*}; ps_inode=${ps_identity#*:}
  [ "$ps_device" != "$ps_identity" ] || exit 1
  case "$ps_inode" in *:*) exit 1;; esac
  package_storage_validate "$ps_path" "$ps_kind" || exit 1
  # An unavailable/replaced volume is not evidence of deletion. Even when DSM
  # has removed the leaf, its captured physical parent must remain available
  # with the same identity before the cleanup journal can be discarded.
  ps_parent_identity=$(sed -n '3p' "$ps_record")
  [ "$(stat -c '%d:%i' "${ps_path%/*}")" = "$ps_parent_identity" ] || exit 1
  if [ -e "$ps_path" ]; then
    [ "$(stat -c '%d:%i' "$ps_path")" = "$ps_identity" ] || exit 1
  fi
)
package_storage_remove() (
  ps_record=$1; ps_kind=$2
  package_storage_verify "$ps_record" "$ps_kind" || exit 1
  ps_path=$(sed -n '1p' "$ps_record")
  if [ -e "$ps_path" ]; then
    # rm unlinks child symlinks without following them. The root-protected
    # parent and recorded identity prevent replacement of the leaf itself.
    rm -rf -- "$ps_path" || exit 1
  fi
  [ ! -e "$ps_path" ] && [ ! -L "$ps_path" ]
)
package_storage_candidates() (
  ps_kind=$1
  case "$ps_kind" in
    var) set -- /volume[0-9]*/@appdata/sadleracme /usr/local/packages/@appdata/sadleracme;;
    etc) set -- /volume[0-9]*/@appconf/sadleracme /usr/syno/etc/packages/sadleracme;;
    *) exit 1;;
  esac
  for ps_path do
    package_storage_scope "$ps_path" "$ps_kind" || continue
    # Include unsafe/broken candidates in diagnostics; validation before any
    # deletion rejects them. No certificate, configuration or log is read.
    if [ -e "$ps_path" ] || [ -L "$ps_path" ]; then printf '%s\n' "$ps_path"; fi
  done
)

# DSM may retain this one root-owned compatibility link after unregistering a
# volume-installed package. Treat it as an alias, never as a recursive-delete
# root. All other candidate symlinks remain forbidden by the physical helpers.
package_storage_alias_target() (
  ps_alias='/usr/syno/etc/packages/sadleracme'
  [ -L "$ps_alias" ] && [ "$(stat -c %u "$ps_alias")" = 0 ] &&
    package_storage_parents "$ps_alias" || exit 1
  ps_target=$(readlink "$ps_alias") || exit 1
  # Require an exact direct absolute volume path, not another alias, relative
  # path or syntactically equivalent path containing traversal components.
  case "$ps_target" in /volume*/@appconf/sadleracme) ;; *) exit 1;; esac
  [ "$(readlink "$ps_alias" | wc -c)" -eq "$(( ${#ps_target} + 1 ))" ] || exit 1
  package_storage_validate "$ps_target" etc || exit 1
  # All target ancestors were validated as physical directories. On a retry
  # the leaf may already be gone, so do not depend on DSM readlink -f accepting
  # a dangling final component after the separately verified data deletion.
  if [ -e "$ps_target" ]; then
    [ "$(readlink -f "$ps_alias")" = "$ps_target" ] || exit 1
  fi
  ps_mounts=$(awk -v p="$ps_alias" '$5==p || index($5,p "/")==1 {print $5}' /proc/self/mountinfo) || exit 1
  [ -z "$ps_mounts" ] || exit 1
  printf '%s\n' "$ps_target"
)
package_storage_alias_capture() (
  ps_record=$1
  ps_alias='/usr/syno/etc/packages/sadleracme'
  ps_record_parent=${ps_record%/*}
  [ -d "$ps_record_parent" ] && [ ! -L "$ps_record_parent" ] &&
    [ "$(stat -c %u "$ps_record_parent")" = 0 ] &&
    [ -z "$(find "$ps_record_parent" -maxdepth 0 \( -perm -020 -o -perm -002 \) -print)" ] || exit 1
  if [ ! -L "$ps_alias" ]; then
    # System-installed packages use a real directory here, handled exclusively
    # by their physical etc manifest. An absent alias needs no unlink record.
    if [ -e "$ps_alias" ]; then
      package_storage_validate "$ps_alias" etc || exit 1
    fi
    # Record this state so a later retry cannot newly authorize an alias
    # which appeared after preparation. Writing the companion first makes an
    # interrupted transition fail closed if both record forms remain.
    ps_tmp=$(mktemp "$ps_record.absent.XXXXXXXX") || exit 1
    trap 'rm -f "$ps_tmp"' EXIT
    printf '%s\n' absent > "$ps_tmp" && chmod 0600 "$ps_tmp" &&
      mv -f "$ps_tmp" "$ps_record.absent" || exit 1
    rm -f -- "$ps_record" || exit 1
    exit 0
  fi
  ps_target=$(package_storage_alias_target) || exit 1
  ps_identity=$(stat -c '%d:%i' "$ps_alias") || exit 1
  ps_parent_identity=$(stat -c '%d:%i' "${ps_alias%/*}") || exit 1
  ps_target_parent_identity=$(stat -c '%d:%i' "${ps_target%/*}") || exit 1
  ps_tmp=$(mktemp "$ps_record.XXXXXXXX") || exit 1
  trap 'rm -f "$ps_tmp"' EXIT
  printf '%s\n%s\n%s\n%s\n%s\n' "$ps_alias" "$ps_identity" "$ps_parent_identity" "$ps_target" "$ps_target_parent_identity" > "$ps_tmp" &&
    chmod 0600 "$ps_tmp" && mv -f "$ps_tmp" "$ps_record" || exit 1
  rm -f -- "$ps_record.absent" || exit 1
)
package_storage_alias_absence_verify() (
  ps_record=$1
  [ -f "$ps_record" ] && [ ! -L "$ps_record" ] &&
    [ "$(stat -c %u "$ps_record")" = 0 ] && [ "$(stat -c %a "$ps_record")" = 600 ] &&
    [ "$(stat -c %s "$ps_record")" = 7 ] && [ "$(wc -l < "$ps_record")" -eq 1 ] &&
    [ "$(cat "$ps_record")" = absent ] || exit 1
  [ ! -L /usr/syno/etc/packages/sadleracme ]
)
package_storage_alias_verify() (
  ps_record=$1
  ps_alias='/usr/syno/etc/packages/sadleracme'
  [ -f "$ps_record" ] && [ ! -L "$ps_record" ] &&
    [ "$(stat -c %u "$ps_record")" = 0 ] && [ "$(stat -c %a "$ps_record")" = 600 ] &&
    [ "$(stat -c %s "$ps_record")" -le 512 ] && [ "$(wc -l < "$ps_record")" -eq 5 ] || exit 1
  [ "$(sed -n '1p' "$ps_record")" = "$ps_alias" ] || exit 1
  ps_identity=$(sed -n '2p' "$ps_record")
  ps_parent_identity=$(sed -n '3p' "$ps_record")
  ps_target=$(sed -n '4p' "$ps_record")
  ps_target_parent_identity=$(sed -n '5p' "$ps_record")
  for ps_check_identity in "$ps_identity" "$ps_parent_identity" "$ps_target_parent_identity"; do
    case "$ps_check_identity" in ''|*[!0-9:]*|:*|*:) exit 1;; esac
    ps_device=${ps_check_identity%%:*}; ps_inode=${ps_check_identity#*:}
    [ "$ps_device" != "$ps_check_identity" ] || exit 1
    case "$ps_inode" in *:*) exit 1;; esac
  done
  case "$ps_target" in /volume*/@appconf/sadleracme) ;; *) exit 1;; esac
  package_storage_parents "$ps_alias" && package_storage_validate "$ps_target" etc || exit 1
  [ "$(stat -c '%d:%i' "${ps_alias%/*}")" = "$ps_parent_identity" ] &&
    [ "$(stat -c '%d:%i' "${ps_target%/*}")" = "$ps_target_parent_identity" ] || exit 1
  # DSM may already have unlinked its compatibility alias. A replacement link
  # or non-link must never inherit this removal authorization.
  if [ -e "$ps_alias" ] || [ -L "$ps_alias" ]; then
    [ -L "$ps_alias" ] && [ "$(stat -c '%d:%i' "$ps_alias")" = "$ps_identity" ] &&
      [ "$(package_storage_alias_target)" = "$ps_target" ] || exit 1
  fi
)
package_storage_alias_remove() (
  ps_record=$1
  package_storage_alias_verify "$ps_record" || exit 1
  ps_alias='/usr/syno/etc/packages/sadleracme'
  if [ -L "$ps_alias" ]; then
    # No slash suffix and no recursive flag: unlink only the recorded alias,
    # whether its separately verified physical target still exists or not.
    rm -f -- "$ps_alias" || exit 1
  fi
  [ ! -e "$ps_alias" ] && [ ! -L "$ps_alias" ]
)
