# AI Production Incident Commander

A production-grade demonstration of autonomous AI incident remediation under the zero-trust governance of **AgentControl**.

---

## Architecture Flow

```
                      Prometheus Alert (High Latency P99)
                                   │
                                   ▼
                       Incident Commander Agent
                                   │
                                   ▼
                   ┌───────────────────────────────┐
                   │       AGENTCONTROL PLANE      │
                   ├───────────────────────────────┤
                   │  1. Inherent Risk Evaluation  │
                   │  2. Declarative Policy Check  │
                   │  3. Multi-Factor Risk Scoring │
                   │  4. Human-in-the-Loop Gating  │
                   │  5. Sandboxed Tool Execution  │
                   │  6. Tamper-Resistant Audit    │
                   └───────────────┬───────────────┘
                                   │
             ┌─────────────────────┼─────────────────────┐
             ▼                     ▼                     ▼
     Read Queries           Pod Inspection          Pod Restart
    (Risk: 0.15/Low)       (Risk: 0.15/Low)      (Risk: 1.0/Critical)
           │                     │                       │
      AUTO-EXEC              AUTO-EXEC             PAUSED FOR SRE
                                                      APPROVAL
                                                         │
                                                   Human Signs Off
                                                         │
                                                    RESUMED &
                                                     EXECUTED
```

---

## Running the Demo

```bash
# Run the end-to-end demonstration script
python examples/incident_commander/incident_commander.py
```

### What You Will Observe:
1. **Low-Risk Auto-Execution**: Read queries to PostgreSQL telemetry run without blocking.
2. **Deterministic Risk Scoring**: The request to execute `kubernetes.restart_pod` on `production/auth-service-789` triggers:
   - Environment baseline: `production` (+0.35)
   - Inherent tool risk: `critical` (+0.35)
   - Destructive keyword: `restart` (+0.25)
   - Sensitive target: `production` (+0.20)
   - Blast radius multiplier (+0.15)
   - **Total Risk Score: 1.0 (CRITICAL)**
3. **Execution Gating**: Tool call status switches to `approval_required`.
4. **Approval Workflow**: A pending approval is created with auto-expiry.
5. **Operator Sign-off**: Senior SRE reviews parameters and approves with rationale.
6. **Audit Verification**: SHA-256 cryptographic hash-chain validates all 28+ events are un-tampered.
