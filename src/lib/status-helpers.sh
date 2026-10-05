# Public hashes report pending configuration without exposing credentials.
publish_applied_signature() {
  applied_value=""
  if [ -s "$APPLIED_SIG" ]; then
    applied_value=$(cat "$APPLIED_SIG")
    case "$applied_value" in *[!0-9a-f]*) applied_value="";; esac
    [ "${#applied_value}" = 64 ] || applied_value=""
  fi
  write_public applied_signature "$applied_value"
}
