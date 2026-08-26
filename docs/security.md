# Security Hardening & Threat Model

A comprehensive overview of security policies, threat modeling, sandboxing, and credential protection across the Mini Server Dashboard ecosystem.

---

## 1. Defense-in-Depth Security Boundaries

```mermaid
flowchart TD
    subgraph ExternalPerimeter["Perimeter & Ingress Security"]
        PublicReq["Incoming HTTP / WebSocket Traffic"] --> NginxShield["Nginx Reverse Proxy (:5173)\n• SSL/TLS Termination\n• Request Size Hard Limits\n• Gzip Payload Sanitization"]
        NginxShield --> JWTIssue{"JWT Bearer Token Valid?"}
    end

    JWTIssue -- "No (401 Unauthorized)" --> RejectReq["Reject Request / Redirect to /login"]
    JWTIssue -- "Yes" --> InternalMesh

    subgraph InternalMesh["Docker Network Isolation (Bridge)"]
        direction TB
        AppContainers["Microservice Containers\n(Metrics, Auth, Files, AI Agent)"]
        DBSecure[("PostgreSQL DB (:5432)\n• Not mapped to host ports\n• Strong password auth\n• Isolated inside bridge")]
        AppContainers <--> DBSecure
    end

    subgraph TargetHostSandbox["Target Linux Server Isolation"]
        Sandbox["Command Sandbox Filter\nRejects destructive patterns:\n• rm -rf /\n• mkfs / dd\n• shutdown / reboot"]
        AppContainers --> Sandbox
        Sandbox --> TargetExec["Execute on Target Linux Host via JSch / AsyncSSH"]
    end
```

---

## 2. Terminal Command Sandbox Pipeline

```mermaid
flowchart LR
    UserInput["Raw Command Input\n(Terminal / AI Agent Tool Call)"] --> Filter1["1. Blacklist Pattern Matcher\nCheck against destructive regex tokens"]
    
    Filter1 --> Match{"Contains Blacklisted Commands?"}
    Match -- "Yes (e.g. rm -rf, :(){ :|:& };:)" --> Block["Block Execution\nReturn 'COMMAND_REJECTED_BY_SECURITY_POLICY'"]
    
    Match -- "No" --> Filter2["2. Timeout Wrapper\nInject 'timeout 15s <cmd>'"]
    Filter2 --> Filter3["3. Execution & Stderr Capture\nStream stdout & log security audits"]
    Filter3 --> Success["Deliver Safe Command Output"]
```

---

## 3. Key Security Protections

1. **Terminal Command Sandboxing:**
   - The Web SSH Terminal and AI Agent execution engines reject destructive commands (`rm -rf /`, `mkfs`, `dd`, `shutdown`, `reboot`).
2. **JWT Authentication & Password Hashing:**
   - Passwords hashed using BCrypt (work factor / cost: 12).
   - JWT tokens signed with HS256 / HS384 using a $\ge 32$-character secret key.
3. **Facebook E2EE Security & PIN Handling:**
   - 6-digit E2EE PIN stored securely in environment / database, never exposed in logs.
   - Persistent browser sessions stored in dedicated Docker volume `browser_data`.
4. **9Router Multi-Key Pool Security:**
   - API keys are masked in logs and status responses (`gsk_...XYZ`).
   - Dynamic key discovery from environment prevents hardcoding secrets.
