# Grade report — public_01_dev

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.347 | +1.5% | 0.243 | +1.5% | 0.501 | +0.3% | 8% | 58 (52) |
| nw_kyc | 0.431 | +14.6% | 0.281 | +16.1% | 0.596 | -2.7% | 0% | 23 (21) |
| nw_renewal | 0.423 | +0.7% | 0.261 | -0.5% | 0.556 | +1.6% | 11% | 50 (39) |
| ALL | 0.390 | +4.0% | 0.257 | +3.5% | 0.541 | +0.4% | 7% | 131 (112) |

## Changes applied by the controller

7 applied — neutral: 2, beneficial: 5

- ks_cancel v2 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=-0.002 didΔ=+0.000 → **neutral**
- nw_renewal v2 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.030 didΔ=+0.000 → **beneficial**
- nw_kyc v2 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.337 → **beneficial**
- nw_kyc v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.001 → **neutral**
- nw_renewal v3 (controller_approved) dims=['cohorts', 'welcome_message'] engageΔ=+0.012 didΔ=+0.000 → **beneficial**
- ks_cancel v3 (controller_approved) dims=['voice'] engageΔ=+0.064 didΔ=+0.000 → **beneficial**
- ks_cancel v4 (controller_approved) dims=['welcome_message'] engageΔ=+0.016 didΔ=+0.000 → **beneficial**

## Governance

```
{
  "approval_requests": 10,
  "decisions": {
    "approved": 7,
    "rejected": 3,
    "expired": 0
  },
  "rejection_reasons": {
    "approver declined (judgement call)": 3
  },
  "applied_via_approval": 7,
  "auto_applied": 0,
  "auto_apply_rejected": 0,
  "apply_conflicts": 0,
  "lapsed": 0,
  "peak_requests_per_24h": {
    "nw_renewal": 1,
    "nw_kyc": 2,
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
    "4": 0.153,
    "5": 0.108,
    "6": 0.086,
    "7": 0.091
  }
}
```

Credits used: 0 · validation runs: 0 · LLM fix calls: 0