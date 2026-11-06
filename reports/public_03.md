# Grade report — public_03_load

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| arav_cancel_2 | 0.362 | +6.3% | 0.244 | -0.2% | 0.525 | +5.5% | 32% | 379 (383) |
| arav_kyc_1 | 0.480 | +33.9% | 0.277 | +28.8% | 0.596 | -0.6% | 0% | 431 (349) |
| arav_renewal_0 | 0.442 | +9.3% | 0.265 | +0.5% | 0.594 | +8.4% | 46% | 463 (458) |
| kest_cancel_2 | 0.364 | +7.4% | 0.244 | -0.2% | 0.531 | +6.8% | 43% | 414 (388) |
| kest_kyc_1 | 0.455 | +28.2% | 0.265 | +24.0% | 0.595 | -0.4% | 0% | 432 (309) |
| kest_renewal_0 | 0.442 | +10.2% | 0.264 | +0.3% | 0.594 | +8.7% | 45% | 424 (430) |
| nort_cancel_2 | 0.362 | +6.6% | 0.243 | -0.3% | 0.527 | +6.0% | 37% | 407 (389) |
| nort_kyc_1 | 0.479 | +35.2% | 0.277 | +29.7% | 0.595 | -0.3% | 0% | 422 (346) |
| nort_renewal_0 | 0.442 | +10.2% | 0.264 | +0.1% | 0.594 | +8.9% | 45% | 441 (431) |
| tide_cancel_2 | 0.364 | +7.1% | 0.244 | -0.2% | 0.529 | +6.0% | 43% | 369 (406) |
| tide_kyc_1 | 0.476 | +34.1% | 0.276 | +29.0% | 0.595 | -0.5% | 0% | 444 (339) |
| tide_renewal_0 | 0.435 | +8.5% | 0.262 | -0.3% | 0.590 | +8.1% | 43% | 445 (422) |
| ALL | 0.425 | +16.3% | 0.260 | +8.2% | 0.573 | +5.2% | 26% | 5071 (4650) |

## Changes applied by the controller

37 applied — beneficial: 29, neutral: 8

- nort_renewal_0 v2 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.030 didΔ=+0.000 → **beneficial**
- tide_cancel_2 v2 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=-0.002 didΔ=+0.000 → **neutral**
- nort_cancel_2 v2 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=-0.002 didΔ=+0.000 → **neutral**
- arav_renewal_0 v2 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.031 didΔ=+0.000 → **beneficial**
- arav_cancel_2 v2 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=-0.002 didΔ=+0.000 → **neutral**
- kest_cancel_2 v2 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=-0.002 didΔ=+0.000 → **neutral**
- arav_kyc_1 v2 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.165 → **beneficial**
- tide_renewal_0 v2 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.031 didΔ=+0.000 → **beneficial**
- nort_kyc_1 v2 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.177 → **beneficial**
- kest_renewal_0 v2 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.030 didΔ=+0.000 → **beneficial**
- kest_kyc_1 v2 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.193 → **beneficial**
- tide_kyc_1 v2 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.201 → **beneficial**
- tide_cancel_2 v3 (controller_approved) dims=['cohorts', 'welcome_message', 'voice'] engageΔ=+0.056 didΔ=+0.000 → **beneficial**
- tide_kyc_1 v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.317 → **beneficial**
- nort_kyc_1 v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.322 → **beneficial**
- nort_cancel_2 v3 (controller_approved) dims=['welcome_message'] engageΔ=+0.037 didΔ=+0.000 → **beneficial**
- arav_renewal_0 v3 (controller_approved) dims=['welcome_message'] engageΔ=+0.093 didΔ=+0.000 → **beneficial**
- kest_cancel_2 v3 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.081 didΔ=+0.000 → **beneficial**
- nort_renewal_0 v3 (controller_approved) dims=['welcome_message'] engageΔ=+0.093 didΔ=+0.000 → **beneficial**
- tide_renewal_0 v3 (controller_approved) dims=['welcome_message'] engageΔ=+0.093 didΔ=+0.000 → **beneficial**
- kest_renewal_0 v3 (controller_approved) dims=['welcome_message'] engageΔ=+0.093 didΔ=+0.000 → **beneficial**
- arav_kyc_1 v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.333 → **beneficial**
- kest_kyc_1 v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.279 → **beneficial**
- nort_cancel_2 v4 (controller_approved) dims=['cohorts', 'voice'] engageΔ=+0.040 didΔ=+0.000 → **beneficial**
- arav_renewal_0 v4 (controller_approved) dims=['cohorts', 'voice'] engageΔ=+0.022 didΔ=+0.000 → **beneficial**
- arav_cancel_2 v3 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.081 didΔ=+0.000 → **beneficial**
- tide_cancel_2 v4 (controller_approved) dims=['cohorts', 'welcome_message', 'voice'] engageΔ=+0.045 didΔ=+0.000 → **beneficial**
- kest_renewal_0 v4 (controller_approved) dims=['cohorts', 'voice'] engageΔ=+0.023 didΔ=+0.000 → **beneficial**
- nort_renewal_0 v4 (controller_approved) dims=['cohorts', 'voice'] engageΔ=+0.022 didΔ=+0.000 → **beneficial**
- tide_kyc_1 v4 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nort_cancel_2 v5 (controller_approved) dims=['voice'] engageΔ=+0.024 didΔ=+0.000 → **beneficial**
- nort_kyc_1 v4 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- arav_cancel_2 v4 (controller_approved) dims=['cohorts', 'welcome_message'] engageΔ=+0.020 didΔ=+0.000 → **beneficial**
- kest_cancel_2 v4 (controller_approved) dims=['cohorts', 'welcome_message'] engageΔ=+0.020 didΔ=+0.000 → **beneficial**
- kest_kyc_1 v4 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=-0.000 → **neutral**
- tide_renewal_0 v4 (controller_approved) dims=['cohorts', 'voice'] engageΔ=+0.023 didΔ=+0.000 → **beneficial**
- arav_cancel_2 v5 (controller_approved) dims=['cohorts', 'welcome_message'] engageΔ=+0.000 didΔ=+0.000 → **neutral**

## Governance

```
{
  "approval_requests": 39,
  "decisions": {
    "approved": 37,
    "rejected": 2,
    "expired": 0
  },
  "rejection_reasons": {
    "approver declined (judgement call)": 2
  },
  "applied_via_approval": 37,
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
    "tide_renewal_0": 1,
    "tide_kyc_1": 1,
    "tide_cancel_2": 1,
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
    "3": 0.85,
    "4": 0.852
  },
  "kest_renewal_0:welcome_message=W3": {
    "3": 0.85,
    "4": 0.85
  },
  "arav_renewal_0:welcome_message=W3": {
    "3": 0.852,
    "4": 0.848
  },
  "tide_renewal_0:welcome_message=W3": {
    "3": 0.849,
    "4": 0.85
  }
}
```

Credits used: 0 · validation runs: 0 · LLM fix calls: 0