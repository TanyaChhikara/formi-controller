# Grade report — public_01_dev

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.348 | +1.8% | 0.241 | +0.5% | 0.506 | +1.3% | 2% | 66 (52) |
| nw_kyc | 0.452 | +19.9% | 0.291 | +20.1% | 0.596 | -2.6% | 0% | 25 (21) |
| nw_renewal | 0.409 | -2.6% | 0.257 | -2.0% | 0.547 | -0.1% | 1% | 51 (39) |
| ALL | 0.390 | +4.0% | 0.256 | +3.3% | 0.540 | +0.3% | 1% | 142 (112) |

## Changes applied by the controller

7 applied — beneficial: 4, neutral: 3

- nw_renewal v2 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.031 didΔ=+0.000 → **beneficial**
- ks_cancel v2 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=-0.002 didΔ=+0.000 → **neutral**
- nw_kyc v2 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.154 → **beneficial**
- nw_kyc v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.193 → **beneficial**
- nw_renewal v3 (controller_approved) dims=['cohorts', 'welcome_message'] engageΔ=+0.005 didΔ=+0.000 → **neutral**
- ks_cancel v3 (controller_approved) dims=['welcome_message'] engageΔ=+0.016 didΔ=+0.000 → **beneficial**
- nw_kyc v4 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=-0.001 → **neutral**

## Governance

```
{
  "approval_requests": 11,
  "decisions": {
    "approved": 7,
    "rejected": 4,
    "expired": 0
  },
  "rejection_reasons": {
    "approver declined (judgement call)": 4
  },
  "applied_via_approval": 7,
  "auto_applied": 0,
  "auto_apply_rejected": 0,
  "apply_conflicts": 0,
  "lapsed": 0,
  "peak_requests_per_24h": {
    "nw_renewal": 1,
    "nw_kyc": 1,
    "ks_cancel": 1
  }
}
```

## Incidents

```
[]
```

## Decaying variants — share of in-population calls still on the variant, by day after onset

```
{
  "nw_renewal:welcome_message=W3": {
    "3": 0.155,
    "4": 0.357,
    "5": 0.482,
    "6": 0.488,
    "7": 0.489
  }
}
```

Credits used: 0 · validation runs: 0 · LLM fix calls: 0