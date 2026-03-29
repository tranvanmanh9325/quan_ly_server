# Security Guide

A thorough review of the security posture of Mini Server Dashboard, covering known trade-offs, risks, hardening recommendations, and incident response procedures.

> [!IMPORTANT]
> This dashboard is designed for **private-network or personal use only**. It has no built-in authentication layer. Read this document before exposing it on any network you do not fully control.

---

## Known Security Trade-offs

The following trade-offs are intentional design decisions, documented here for complete transparency.

### 1. No API Authentication

**Risk:** All `/api/metrics/*` endpoints are publicly accessible to anyone who can reach port `8080` or `5173`.

**Accepted because:** The dashboard is intended to run inside a home network, behind a firewall, or behind a VPN. Exposing a monitoring dashboard to an attacker is problematic regardless of authentication, since it reveals system topology and resource usage.

**Mitigation if you need to expose it publicly:**

- Add Spring Security with HTTP Basic auth or JWT.
- Use an Nginx `auth_basic` block in front of the dashboard.
- Put the entire stack behind a VPN (WireGuard, Tailscale).

---

### 2. `StrictHostKeyChecking=no`

**Location:** `SshService.java` → `config.put("StrictHostKeyChecking", "no")`

**Risk:** Disables SSH host key verification. A man-in-the-middle attacker on the network path between the backend container and the target server could intercept credentials.

**Accepted because:** Ngrok TCP tunnels assign a new host key on every reconnect. Strict checking would break the connection each time the Ngrok tunnel restarts.

**Mitigation for stable production environments:**
Remove the `StrictHostKeyChecking=no` setting and add the known host fingerprint:

```java
// In SshService.getOrCreateSession()
JSch jsch = new JSch();
jsch.setKnownHosts("/path/to/known_hosts");  // or use addHostKey()
Session session = jsch.getSession(user, host, port);
// Remove: config.put("StrictHostKeyChecking", "no");
```

---

### 3. Password-Based SSH Authentication

**Risk:** SSH passwords are stored in plain text in `backend/.env` and injected as environment variables. Passwords are susceptible to brute-force attacks if the SSH port is exposed.

**Accepted because:** Password auth is the quickest setup for a personal dashboard where the SSH target is already on a private network.

**Recommended production alternative — SSH key-pair authentication:**

```java
// In SshService.getOrCreateSession()
JSch jsch = new JSch();
jsch.addIdentity("/path/to/private_key");  // no passphrase, or add passphrase as second arg
Session session = jsch.getSession(user, host, port);
// Remove: session.setPassword(password);
```

Store the private key path (not the key content itself) in the `.env` file and add it to `.gitignore`.

---

### 4. CORS Wildcard vs. Explicit Headers

**Location:** `CorsConfig.java`

The config uses an explicit `allowedHeaders` list (`Content-Type`, `Accept`, `Authorization`, `X-Requested-With`) instead of the `allowedHeaders("*")` wildcard.

**Why:** When combined with `allowCredentials(true)`, the CORS specification does not permit a wildcard header list. Browsers reflect all request headers when `*` is used, which violates the spec and can be rejected.

This is already correctly implemented and requires no further action.

---

## `.env` File Security

The `backend/.env` file holds SSH credentials. It is the most sensitive file in the project.

### Prevention Checklist

- [ ] `.env` is listed in `backend/.gitignore` ✅ (already done)
- [ ] `.env` is **never** committed to the repository

### Verify: Confirm `.env` Was Never Committed

```bash
git log --all --full-history -- backend/.env
```

If this command produces any output, the file was committed at some point. See the remediation steps below.

### Remediation: If `.env` Was Accidentally Committed

1. **Immediately rotate your SSH credentials** on the target server — treat the old credentials as compromised.
2. Remove the file from Git history:

   ```bash
   pip install git-filter-repo
   git filter-repo --path backend/.env --invert-paths
   ```

3. Force-push the cleaned history:

   ```bash
   git push origin --force --all
   git push origin --force --tags
   ```

4. Ask all collaborators to re-clone the repository (their local copies still contain the old history).

---

## Network Exposure

### Port Exposure Summary

| Port | Service | Default Exposure | Recommendation |
| --- | --- | --- | --- |
| `5173` | Nginx (Dashboard UI) | Host-level | Bind to `127.0.0.1` or firewall if not serving externally |
| `8080` | Spring Boot (API) | Host-level | **Do not expose publicly** without an auth layer |

### Recommended Firewall Rules (UFW example)

```bash
# Allow dashboard UI only from your home network
sudo ufw allow from 192.168.1.0/24 to any port 5173
sudo ufw deny 5173

# Block backend port from all external access
sudo ufw deny 8080
```

---

## Actuator Hardening

Spring Boot Actuator is included for the `/actuator/health` Docker healthcheck. Only the `health` endpoint is exposed and it reveals no implementation details:

```properties
management.endpoints.web.exposure.include=health
management.endpoint.health.show-details=never
```

This means `/actuator/beans`, `/actuator/env`, `/actuator/info`, and all other Actuator endpoints are not accessible. This is the correct configuration.

---

## Docker Security

### Container Isolation

Both containers run on an isolated `dashboard-network` bridge network. They can communicate with each other by container name (`backend`) but are not exposed to other containers or the host network by default.

### Privilege Reduction

Consider running the Spring Boot JVM as a non-root user in the container. Add to the backend `Dockerfile`:

```dockerfile
FROM eclipse-temurin:21-jre-alpine
RUN addgroup -S appgroup && adduser -S appuser -G appgroup
WORKDIR /app
RUN apk add --no-cache wget
COPY --from=builder /app/target/dashboard-0.0.1-SNAPSHOT.jar app.jar
USER appuser         # <-- drop root privileges
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "app.jar"]
```

### Image Updates

Dependabot is configured to open weekly PRs for Docker base image updates. Keeping these images current is important for security patches in:

- `maven:3.9.6-eclipse-temurin-21` (build stage)
- `eclipse-temurin:21-jre-alpine` (runtime)
- `node:20-alpine` (frontend build)
- `nginx:alpine` (frontend runtime)

---

## Secrets Management — Future Hardening

For a more hardened production setup, consider migrating from file-based secrets to:

| Option | Complexity | Notes |
| --- | --- | --- |
| Docker secrets | Low | Native to Docker Swarm; less convenient with Compose standalone |
| HashiCorp Vault | High | Enterprise-grade; adds a lot of infrastructure overhead |
| Environment variables (injected by the CI runner) | Low | Already used via the self-hosted runner; keep `.env` off-disk |
| SSH key-pair (no password) + key stored on server | Low | Best improvement with the least effort |

The recommended quick win is switching to **SSH key-pair authentication** (see above) and storing only the key path in `.env`, not the key content.

---

## Vulnerability Reporting

Please do **not** open a public GitHub Issue for security vulnerabilities.

Instead, use GitHub's private **Security Advisory** feature:
**Repository → Security → Advisories → Report a vulnerability**

Response SLA: 7 days acknowledgement, 30 days fix for confirmed vulnerabilities.

For the full reporting policy, see [SECURITY.md](../SECURITY.md).
