# Free uptime monitoring and alerts

`deploy/scripts/monitor.sh` probes the API liveness/readiness endpoints and, when supplied, the
customer-agent liveness and Agent Card. It fails nonzero if any public HTTPS surface is unavailable,
so the same command works with a free scheduled GitHub Actions job and GitHub's built-in failed-run
notifications without adding a monitoring credential.

```bash
bash deploy/scripts/monitor.sh \
  https://api.example.com \
  https://agent.example.com
```

The coordinator-owned workflow should run every five minutes, use only public origins stored as
non-secret repository variables, grant `contents: read`, set a five-minute timeout, and open/notify
on consecutive failures. The monitor should live outside the OCI VM so a VM/network outage is still
observable.

## On-host diagnostic timer

The systemd files under `infra/monitoring` provide a no-credential two-minute diagnostic probe. They
are secondary evidence, not external availability monitoring.

```bash
sudo install -m 0644 infra/monitoring/recoveryos-uptime.service /etc/systemd/system/
sudo install -m 0644 infra/monitoring/recoveryos-uptime.timer /etc/systemd/system/
sudo install -m 0600 /dev/null /etc/recoveryos/monitoring.env
sudoedit /etc/recoveryos/monitoring.env
sudo systemctl daemon-reload
sudo systemctl enable --now recoveryos-uptime.timer
systemctl list-timers recoveryos-uptime.timer
```

`monitoring.env` contains only public values:

```text
API_BASE_URL=https://api.example.com
CUSTOMER_AGENT_BASE_URL=https://agent.example.com
```

Review failures with `journalctl -u recoveryos-uptime.service --since -30min`. Do not log headers,
provider payloads, transcripts, or environment output.
