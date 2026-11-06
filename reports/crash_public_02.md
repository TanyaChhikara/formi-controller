# Grade report — public_02_incidents

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.313 | +28.3% | 0.218 | +19.3% | 0.498 | +5.5% | 34% | 86 (310) |
| nw_kyc | 0.447 | +16.4% | 0.289 | +16.7% | 0.587 | -2.0% | 0% | 27 (38) |
| nw_renewal | 0.426 | -1.0% | 0.258 | -1.8% | 0.549 | +0.2% | 4% | 48 (58) |
| ALL | 0.379 | +12.9% | 0.246 | +10.1% | 0.537 | +1.2% | 20% | 161 (406) |

## Changes applied by the controller

16 applied — beneficial: 13, neutral: 3

- nw_renewal v2 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.019 didΔ=+0.000 → **beneficial**
- ks_cancel v2 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.010 didΔ=+0.000 → **beneficial**
- nw_kyc v2 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.147 → **beneficial**
- ks_cancel v3 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.192 → **beneficial**
- ks_cancel v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.161 → **beneficial**
- ks_cancel v5 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.069 → **beneficial**
- ks_cancel v6 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.062 → **beneficial**
- ks_cancel v7 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.057 → **beneficial**
- ks_cancel v8 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.053 → **beneficial**
- ks_cancel v9 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.049 → **beneficial**
- ks_cancel v10 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.046 → **beneficial**
- ks_cancel v11 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- ks_cancel v13 (controller_approved) dims=['prompt_version'] engageΔ=+0.102 didΔ=+0.000 → **beneficial**
- nw_kyc v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.194 → **beneficial**
- nw_kyc v4 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=-0.001 → **neutral**
- nw_renewal v4 (controller_approved) dims=['voice'] engageΔ=-0.008 didΔ=+0.000 → **neutral**

## Governance

```
{
  "approval_requests": 9,
  "decisions": {
    "approved": 7,
    "rejected": 2,
    "expired": 0
  },
  "rejection_reasons": {
    "approver declined (judgement call)": 2
  },
  "applied_via_approval": 7,
  "auto_applied": 9,
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
[
  {
    "type": "did_flagged",
    "workflow": "ks_cancel",
    "at": "D2 10:00",
    "flagged_did_share_by_day": {
      "2": 0.141,
      "3": 0.0,
      "4": 0.0,
      "5": 0.0,
      "6": 0.0,
      "7": 0.0,
      "8": 0.0,
      "9": 0.0
    }
  },
  {
    "type": "supervisor_edit",
    "workflow": "ks_cancel",
    "at": "D3 11:30",
    "mttr_minutes": 210,
    "fixed_by": "controller_approved"
  },
  {
    "type": "supervisor_edit",
    "workflow": "nw_renewal",
    "at": "D5 15:00"
  }
]
```

## Decaying variants — share of in-population calls still on the variant, by day after onset

```
{
  "nw_renewal:welcome_message=W3": {
    "2": 0.155,
    "3": 0.158,
    "4": 0.156,
    "5": 0.151,
    "6": 0.152,
    "7": 0.14,
    "8": 0.16,
    "9": 0.148
  }
}
```

Credits used: 3 · validation runs: 1 · LLM fix calls: 0