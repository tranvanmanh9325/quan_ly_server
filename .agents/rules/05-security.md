# Rule 05 — Security Constraints

## Threat Model

This is a **personal, private-network tool**. The threat model assumes:

- The application runs behind a firewall or private VPN.
- Only the owner (or explicitly trusted users) can reach port 5173.
- The remote server is under the owner's control.

These assumptions justify the trade-offs below. If your deployment
changes (e.g. you expose the dashboard to the internet), the trade-offs
**no longer apply** — redesign the security posture accordingly.

---

## Known & Accepted Trade-offs

| Area | Decision | Condition for re-evaluation |
| --- | --- | --- |
| `StrictHostKeyChecking=no` | Required for Ngrok (host key changes on reconnect) | Switch to a fixed IP or VPN → enable strict checking |
| No auth on `/api/**` | By design; private-network-only | Any public deployment |
| SSH password auth | Simpler for personal setup | Consider key-based auth for shared deployments |
| SSH over Ngrok | Credentials transit a third-party tunnel | Use direct SSH or VPN for sensitive data |

---

## What Must Never Change Without Explicit Review

1. **Do not add `allowedOrigins("*")` to `CorsConfig`.** Production traffic
   never triggers CORS (Nginx handles it), so there is no legitimate reason
   to widen the origin list.

2. **Do not expose backend port 8080 in `docker-compose.yml` to `0.0.0.0`.**
   The current `"8080:8080"` binding IS accessible on all interfaces — this
   is a known risk. The host firewall must block external access to this port.
   A safer future change is to bind it to `127.0.0.1:8080:8080`.

3. **Never log SSH credentials** (`host`, `user`, `password`) at any log level.
   The `log.info(...)` in `getOrCreateSession()` logs user and host only —
   the password must never appear in logs.

4. **Never echo the `password` field in any API response.**

5. **Do not add a `/api/health` or `/actuator/**` endpoint that reveals
   internal state** (env variables, config props, beans) to the network.
   Actuator is included for the healthcheck probe only.
   If Actuator web endpoints are expanded, restrict them via
   `management.endpoints.web.exposure.include`.

---

## Sensitive File Checklist

Before every commit, verify:

- [ ] `backend/.env` is in `.gitignore` and NOT staged.
- [ ] `backend/.env.example` has no real values — only placeholders.
- [ ] No credentials appear in any log file committed to the repo.
- [ ] No hardcoded IPs, hostnames, or usernames in source code.

---

## Future Hardening Recommendations

These are not currently required but should be considered if the project
evolves toward a shared or internet-facing deployment:

- **Add authentication**: HTTP Basic Auth in Nginx, or a Spring Security
  layer with session or JWT. The simplest addition with the current stack
  is Nginx `auth_basic`.
- **Use SSH key authentication**: Replace `ssh.password` with
  `ssh.privateKeyPath` + `session.setIdentity(...)` to eliminate
  password-over-Ngrok risk.
- **Bind backend port to loopback**: In `docker-compose.yml`, change
  `"8080:8080"` to `"127.0.0.1:8080:8080"` so only the host machine
  (and the Nginx container on the bridge network) can reach the backend.
- **Enable `StrictHostKeyChecking`**: Store the known host key in a local
  `known_hosts` file and mount it into the container. This eliminates the
  MITM window during SSH negotiation.
- **Rate-limit the Nginx proxy**: Add `limit_req_zone` to `nginx.conf`
  to protect `/api/*` from being hammered externally.
- **Add Actuator security**: Set
  `management.endpoints.web.exposure.include=health` only, and consider
  binding Actuator to a separate management port that is not forwarded
  through Nginx.
