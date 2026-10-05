# Read the timer manager's reported deadline. This is display metadata only:
# never start/restart a unit, change settings, or infer a deadline from a run.
renewal_timer_deadline() (
  rtd_listing=$(LC_ALL=C TZ=UTC systemctl list-timers --all --no-pager --full 2>/dev/null) || exit 1
  rtd_stamp=$(printf '%s\n' "$rtd_listing" | LC_ALL=C awk '
    NF >= 2 && $(NF-1)=="pkg-sadleracme-renew.timer" && $NF=="pkg-sadleracme-renew.service" {
      matches++
      if ($1 ~ /^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)$/ &&
          $2 ~ /^[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]$/ &&
          $3 ~ /^[0-9][0-9]:[0-9][0-9]:[0-9][0-9]$/ && $4=="UTC")
        stamp=$1 " " $2 " " $3 " " $4
      else invalid=1
    }
    END { if (matches!=1 || invalid || stamp=="") exit 1; print stamp }
  ') || exit 1
  if rtd_parsed=$(LC_ALL=C TZ=UTC date -u -d "$rtd_stamp" '+%a %Y-%m-%d %H:%M:%S UTC|%s' 2>/dev/null); then
    :
  else
    # Older DSM BusyBox date may require an explicit input format. Both paths
    # parse in UTC and return a normalized timestamp with its epoch together.
    rtd_parsed=$(LC_ALL=C TZ=UTC date -u -D '%a %Y-%m-%d %H:%M:%S %Z' -d "$rtd_stamp" '+%a %Y-%m-%d %H:%M:%S UTC|%s' 2>/dev/null) || exit 1
  fi
  rtd_epoch=${rtd_parsed##*|}
  case "$rtd_epoch" in ''|*[!0-9]*) exit 1;; esac
  [ "${#rtd_epoch}" -le 10 ] && [ "$rtd_epoch" -gt 0 ] || exit 1
  # Reject dates or weekdays that date might normalize instead of accepting
  # the exact UTC timestamp reported by systemd.
  [ "$rtd_parsed" = "$rtd_stamp|$rtd_epoch" ] || exit 1
  printf '%s\n' "$rtd_epoch"
)

refresh_renewal_deadline() {
  rrd_epoch=''
  if [ "${1:-}" = active ] && [ -f "$RUN_MARKER" ] &&
      [ ! -f "$ROOT_STATE/setup-temporary" ] &&
      [ ! -f "$ROOT_STATE/uninstall-ready" ] &&
      [ ! -f "$ROOT_STATE/wizard-apply.pending" ]; then
    # Missing/unavailable NEXT (including an executing oneshot), unsupported
    # output and query failures are nonfatal. A later status refresh retries.
    rrd_epoch=$(renewal_timer_deadline) || rrd_epoch=''
  fi
  # Cache the actual timer even while automatic renewal is disabled. The CGI
  # hides it in that state, then can show it immediately when settings enable
  # renewal. Only the privileged worker writes this public status file.
  write_public next_auto_epoch "$rrd_epoch"
}
