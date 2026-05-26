#!/usr/bin/env bash
# Capa 7 (DEPLOY_VPS_PLAN.md): host disk usage alert.
#
# Runs hourly from cron. If any monitored filesystem exceeds threshold,
# POSTs a JSON payload to a webhook URL (Slack-compatible, Discord, or
# Healthchecks.io fail URL).
#
# Configuration (env or cron line):
#   ALERT_THRESHOLD     percent before alert      default 80
#   ALERT_WEBHOOK       URL to POST on alert      default "" (no alert, just log)
#   ALERT_MOUNTS        space-separated mounts    default "/ /var/lib/docker /var/backups/vet"
#   HOST_LABEL          label in payload          default $(hostname)
#
# Exit codes:
#   0  all mounts under threshold
#   1  alert sent (>= threshold on at least one mount)
#   2  webhook POST failed
#
# Example cron line (hourly):
#   15 * * * * ALERT_WEBHOOK=https://hooks.slack.com/services/... /opt/vet/app/scripts/disk-alert.sh

set -euo pipefail

ALERT_THRESHOLD="${ALERT_THRESHOLD:-80}"
ALERT_WEBHOOK="${ALERT_WEBHOOK:-}"
ALERT_MOUNTS="${ALERT_MOUNTS:-/ /var/lib/docker /var/backups/vet}"
HOST_LABEL="${HOST_LABEL:-$(hostname)}"

log() { printf '[disk-alert] %s\n' "$*"; }

OVER=()
for MOUNT in $ALERT_MOUNTS; do
  if [ ! -d "$MOUNT" ]; then
    continue
  fi
  USED=$(df --output=pcent "$MOUNT" 2>/dev/null | tail -1 | tr -d ' %')
  if [ -z "$USED" ]; then
    continue
  fi
  log "$MOUNT used=${USED}%"
  if [ "$USED" -ge "$ALERT_THRESHOLD" ]; then
    OVER+=("$MOUNT=${USED}%")
  fi
done

if [ ${#OVER[@]} -eq 0 ]; then
  log "all under threshold ($ALERT_THRESHOLD%)"
  exit 0
fi

# At least one mount over threshold.
MSG="DISK ALERT $HOST_LABEL — over ${ALERT_THRESHOLD}%: ${OVER[*]}"
log "$MSG"

if [ -z "$ALERT_WEBHOOK" ]; then
  log "ALERT_WEBHOOK empty — skipping notify"
  exit 1
fi

# Slack-compatible payload (Discord also accepts via Slack-format URL with
# `/slack` suffix). For Healthchecks.io: just plain POST works too.
PAYLOAD=$(printf '{"text":"%s"}' "$MSG")

if curl -fsS -m 10 --retry 3 \
     -H 'Content-Type: application/json' \
     -d "$PAYLOAD" \
     "$ALERT_WEBHOOK" \
     -o /dev/null; then
  log "webhook POST OK"
  exit 1
else
  log "webhook POST FAILED"
  exit 2
fi
