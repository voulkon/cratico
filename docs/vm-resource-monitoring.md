# VM Resource Monitoring — Quick Stats Logger

Lightweight cron + logrotate setup for capturing per-container `docker stats`
snapshots over time, without deploying Prometheus/cAdvisor. Useful for sizing
decisions on a new VM before/instead of standing up the full metrics stack.

## Setup

1. **Create the collector script.** Adjust the `grep` filter (or remove it) to
   scope to the containers you care about on that host — e.g. `iwwc` for the
   preview stack, or leave it unfiltered on a single-purpose VM (like a DB VM).

   ```bash
   cat << 'EOF' | sudo tee /usr/local/bin/docker-stats-log.sh > /dev/null
   #!/bin/sh
   TS=$(date '+%Y-%m-%d %H:%M:%S')
   docker stats --no-stream --format "{{.Name}} {{.CPUPerc}} {{.MemUsage}} {{.NetIO}}" \
     | while read -r line; do echo "$TS $line"; done >> /var/log/docker-stats.log
   EOF
   sudo chmod +x /usr/local/bin/docker-stats-log.sh
   ```

   Note: plain `sudo cat ... > file` does **not** work — `sudo` only applies to
   `cat`, while the `>` redirection is performed by your (non-root) shell and
   fails with `Permission denied`. `sudo tee` (or `sudo sh -c 'cat > file'`)
   is the correct pattern for writing root-owned files as a non-root user.

2. **Register the cron job.** `/etc/cron.d/` entries require an explicit user
   field (`root` below) — omitting it causes a silent "bad command" syntax
   error and the job never runs.

   ```bash
   echo "*/5 * * * * root /usr/local/bin/docker-stats-log.sh" | sudo tee /etc/cron.d/docker-stats
   sudo chmod 644 /etc/cron.d/docker-stats
   ```

3. **Verify it's firing.** Cron logs to journald on modern Ubuntu, not
   `/var/log/syslog` — check there first.

   ```bash
   journalctl -u cron --since "10 minutes ago"   # look for CMD (/usr/local/bin/docker-stats-log.sh)
   ls -la /var/log/docker-stats.log
   ```

4. **Add logrotate.** Needed `su root root` here because the host's
   `/var/log` had group/world-writable parent permissions, which logrotate
   refuses to rotate into without an explicit user directive.

   ```bash
   cat << 'EOF' | sudo tee /etc/logrotate.d/docker-stats > /dev/null
   /var/log/docker-stats.log {
       daily
       rotate 14
       compress
       delaycompress
       missingok
       notifempty
       create 0644 root root
       su root root
   }
   EOF
   ```

5. **Test.**

   ```bash
   sudo logrotate -d /etc/logrotate.d/docker-stats   # dry run, should print no errors
   sudo logrotate -f /etc/logrotate.d/docker-stats   # force a rotation to confirm it works end-to-end
   ```

## Reading the data

```bash
scp -i ~/.ssh/id_ed25519 root@$VM_IP:/var/log/docker-stats.log* ~/Downloads/
```

Then analyze with `scripts/analyze_docker_stats.py` (requires pandas; optional
matplotlib for `--plot`). It parses the log format (`timestamp container
CPU% mem-used / mem-limit net-in / net-out`) and reports per-container
memory/CPU mean/max/std, CPU spikes, and — the key sizing number — the
whole-stack memory sum per timestamp:

```bash
python3 scripts/analyze_docker_stats.py ~/Downloads/docker-stats.log
# multiple / rotated logs, strip the stack suffix from container names:
python3 scripts/analyze_docker_stats.py ~/Downloads/docker-stats.log* --by-name
# generate a memory + CPU timeline chart:
python3 scripts/analyze_docker_stats.py ~/Downloads/docker-stats.log* --by-name --plot stats.png
# filter to one container for a focused look:
python3 scripts/analyze_docker_stats.py ~/Downloads/docker-stats.log* --by-name | less
```

Quick ad-hoc checks without the script: `grep` a container's name, or use
`awk` to sum memory per timestamp for sizing. Check CPU spikes against the
schedule of Celery beat ingestion runs to attribute load.

The whole-stack sum per timestamp across
containers is the number that drives server sizing.

## Uninstalling

```bash
sudo rm -f /etc/cron.d/docker-stats
sudo rm -f /etc/logrotate.d/docker-stats
sudo rm -f /var/log/docker-stats.log*   # also removes rotated/compressed copies
```

No service restart is needed — cron picks up the removal automatically.

## When to prefer the full Prometheus + cAdvisor + Grafana stack instead

This approach is a quick, zero-dependency baseline. Once you need historical
dashboards, alerting, or per-container breakdowns over weeks, use the
`resource-monitoring` compose profile (`cadvisor` + `prometheus` services)
already wired into `docker/docker-compose.yml` and
`docker-compose.prod-no-db.yml`, provisioned into the existing Grafana
instance via `docker/grafana-provisioning/`.
