# Grade report — public_03_load

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| arav_cancel_2 | 0.359 | +5.5% | 0.243 | -0.6% | 0.524 | +5.3% | 37% | 419 (383) |
| arav_kyc_1 | 0.479 | +33.6% | 0.277 | +29.0% | 0.592 | -1.2% | 0% | 420 (349) |
| arav_renewal_0 | 0.435 | +7.7% | 0.264 | +0.2% | 0.585 | +6.7% | 34% | 419 (458) |
| kest_cancel_2 | 0.359 | +6.1% | 0.244 | +0.0% | 0.522 | +5.0% | 32% | 369 (388) |
| kest_kyc_1 | 0.479 | +35.0% | 0.278 | +30.3% | 0.593 | -0.8% | 0% | 448 (309) |
| kest_renewal_0 | 0.441 | +10.0% | 0.265 | +0.8% | 0.590 | +7.9% | 43% | 437 (430) |
| nort_cancel_2 | 0.369 | +8.8% | 0.244 | -0.1% | 0.535 | +7.6% | 50% | 406 (389) |
| nort_kyc_1 | 0.476 | +34.2% | 0.276 | +29.2% | 0.594 | -0.4% | 0% | 444 (346) |
| nort_renewal_0 | 0.439 | +9.5% | 0.263 | -0.1% | 0.592 | +8.5% | 47% | 431 (431) |
| tide_cancel_2 | 0.359 | +5.6% | 0.244 | -0.4% | 0.522 | +4.6% | 33% | 403 (406) |
| tide_kyc_1 | 0.477 | +34.3% | 0.276 | +29.1% | 0.596 | -0.3% | 0% | 420 (339) |
| tide_renewal_0 | 0.439 | +9.4% | 0.264 | +0.4% | 0.588 | +7.8% | 42% | 458 (422) |
| ALL | 0.426 | +16.5% | 0.261 | +8.7% | 0.571 | +4.7% | 25% | 5074 (4650) |

## Changes applied by the controller

35 applied — neutral: 8, beneficial: 27

- nort_cancel_2 v2 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=-0.002 didΔ=+0.000 → **neutral**
- tide_cancel_2 v2 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=-0.002 didΔ=+0.000 → **neutral**
- arav_cancel_2 v2 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=-0.002 didΔ=+0.000 → **neutral**
- arav_renewal_0 v2 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.030 didΔ=+0.000 → **beneficial**
- kest_renewal_0 v2 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.030 didΔ=+0.000 → **beneficial**
- nort_renewal_0 v2 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.030 didΔ=+0.000 → **beneficial**
- tide_kyc_1 v2 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.185 → **beneficial**
- tide_renewal_0 v2 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.031 didΔ=+0.000 → **beneficial**
- kest_kyc_1 v2 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.193 → **beneficial**
- nort_kyc_1 v2 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.197 → **beneficial**
- arav_kyc_1 v2 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.197 → **beneficial**
- nort_cancel_2 v3 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.103 didΔ=+0.000 → **beneficial**
- nort_renewal_0 v3 (controller_approved) dims=['welcome_message'] engageΔ=+0.093 didΔ=+0.000 → **beneficial**
- nort_kyc_1 v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.317 → **beneficial**
- arav_cancel_2 v3 (controller_approved) dims=['welcome_message'] engageΔ=+0.016 didΔ=+0.000 → **beneficial**
- kest_cancel_2 v2 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=-0.002 didΔ=+0.000 → **neutral**
- kest_kyc_1 v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.327 → **beneficial**
- tide_kyc_1 v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.333 → **beneficial**
- tide_renewal_0 v3 (controller_approved) dims=['welcome_message'] engageΔ=+0.093 didΔ=+0.000 → **beneficial**
- kest_renewal_0 v3 (controller_approved) dims=['welcome_message'] engageΔ=+0.093 didΔ=+0.000 → **beneficial**
- arav_kyc_1 v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.374 → **beneficial**
- tide_cancel_2 v3 (controller_approved) dims=['welcome_message'] engageΔ=+0.016 didΔ=+0.000 → **beneficial**
- arav_cancel_2 v4 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.085 didΔ=+0.000 → **beneficial**
- tide_cancel_2 v4 (controller_approved) dims=['voice'] engageΔ=+0.064 didΔ=+0.000 → **beneficial**
- kest_cancel_2 v3 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.081 didΔ=+0.000 → **beneficial**
- nort_renewal_0 v4 (controller_approved) dims=['cohorts', 'voice'] engageΔ=+0.022 didΔ=+0.000 → **beneficial**
- kest_renewal_0 v4 (controller_approved) dims=['cohorts', 'voice'] engageΔ=+0.022 didΔ=+0.000 → **beneficial**
- arav_renewal_0 v3 (controller_approved) dims=['cohorts', 'welcome_message', 'voice'] engageΔ=+0.117 didΔ=+0.000 → **beneficial**
- nort_kyc_1 v4 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=-0.000 → **neutral**
- kest_kyc_1 v4 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- kest_cancel_2 v4 (controller_approved) dims=['cohorts', 'welcome_message'] engageΔ=+0.020 didΔ=+0.000 → **beneficial**
- tide_kyc_1 v4 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=-0.000 → **neutral**
- tide_cancel_2 v5 (controller_approved) dims=['welcome_message'] engageΔ=+0.020 didΔ=+0.000 → **beneficial**
- tide_renewal_0 v4 (controller_approved) dims=['cohorts', 'voice'] engageΔ=+0.022 didΔ=+0.000 → **beneficial**
- arav_kyc_1 v4 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=-0.000 → **neutral**

## Governance

```
{
  "approval_requests": 39,
  "decisions": {
    "approved": 35,
    "rejected": 4,
    "expired": 0
  },
  "rejection_reasons": {
    "approver declined (judgement call)": 4
  },
  "applied_via_approval": 35,
  "auto_applied": 0,
  "auto_apply_rejected": 0,
  "apply_conflicts": 0,
  "lapsed": 0,
  "peak_requests_per_24h": {
    "nort_renewal_0": 1,
    "nort_kyc_1": 1,
    "nort_cancel_2": 1,
    "arav_renewal_0": 1,
    "arav_kyc_1": 1,
    "arav_cancel_2": 1,
    "tide_renewal_0": 2,
    "tide_kyc_1": 1,
    "tide_cancel_2": 2,
    "kest_renewal_0": 1,
    "kest_kyc_1": 1,
    "kest_cancel_2": 1
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
  "nort_renewal_0:welcome_message=W3": {
    "3": 0.847,
    "4": 0.849
  },
  "kest_renewal_0:welcome_message=W3": {
    "3": 0.851,
    "4": 0.852
  },
  "arav_renewal_0:welcome_message=W3": {
    "3": 0.853,
    "4": 0.851
  },
  "tide_renewal_0:welcome_message=W3": {
    "3": 0.852,
    "4": 0.85
  }
}
```

Credits used: 0 · validation runs: 0 · LLM fix calls: 0