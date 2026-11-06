# Outcome-First Agent Loop — Submission

**Name:** Gourab · **Date:** 2026-11-06 · **Hours actually spent:** ~7, in one day, AI-assisted (every line reviewed) · **Language / storage:** Python 3.11+, httpx, SQLite (WAL, one file)

---

## 0. TL;DR
- A single-process controller: ingests events into counters in SQLite, runs four state-driven policies (supervisor edits, hallucination incidents, caller-ID health, welcome/voice/caller-ID experiments) and sends every change through one governance client.
- **public_01: +5.4% leads concluded vs baseline, 7 changes applied, 0 harmful. public_02: +16.2%, 18 changes, 0 harmful, bad prompt fixed in 180 min, flagged caller ID at 0% from the next day. public_03 (load): +16.3%, 37 changes, 0 harmful, ~24 s wall per simulated day.**
- Crash test: 6–8 random `kill -9`s per run; every event counted once, no approval applied twice or lost, nothing lapsed.
- Deliberately not built: per-person call time (C4), cross-tenant fairness (C15), a UI (C11 is a JSON/CLI view).

## 1. Assumptions
1. `engagement_rate_max_drop: 0.02` / `pickup_rate_max_drop: 0.02` are absolute (percentage points).
1. The approver's identity isn't exposed by the API, so "who approved" = the workflow's client approver + `approval_id` + timestamps. In production this would be a named user.
2. Engagement levers are welcome message and voice; pickup levers are caller ID (and schedule). So engagement-primary workflows test welcome/voice and pickup-primary workflows test caller ID. I don't test welcome/voice on pickup-primary workflows (no effect on their primary KPI, and it would spend their 2/day approval budget).
3. "Customer-facing" = welcome, voice, prompt, cohorts. Even where policy allows auto-applying them (Kestrel), I send them for approval (see §6).
4. A caller ID whose pickup collapses relative to its peers over a 3-hour population is bad. Quarantine is permanent for the run (no re-admission yet; see §13).
5. Spam flagging is driven by volume per number (standard dialler practice). So when caller ID is the lever, the "winner" gets at most 60% and the rest is spread.
6. The supervisor memos describe real client preferences, so I encode them as stricter-than-policy limits (`CLIENT_PREFS` in `governance.py`). They are keyed by tenant, so hidden scenarios with other tenants just get the policy.
7. Prompts: one per workflow, so prompts are not A/B tested. A prompt only changes to fix an incident, with validation evidence.
8. History (pre-D0) ran on the default config, so it gives baselines (hallucination rate, per-DID pickup, KPI levels), not variant rankings.

## 2. Scope decisions
| # | Capability | Built / Partial / Cut | Why | What it would take to finish |
|---|---|---|---|---|
| C1 | Ingestion | **Built** | Everything rests on it; crash safety starts here | Partition by tenant at 10× (§8) |
| C2 | Shared cohort object | **Built** | Cohorts are created in one place (segment winner / harmed segment), stored in `cohorts`, and used in config, stats keys and the view | Two-feature segments; merging cohorts |
| C3 | Bootstrap from history | Partial | Baselines only; history has no variant data | — |
| C4 | Call-time optimisation | **Cut** | Per person: 2–8 attempts per person, 20–40% returning → noise. Per cohort: needs `cohorts` changes (approval) for a guardrail-only gain | Per-cohort `hour_weights` from history pickup-by-hour, batched into a cohort proposal |
| C5 | Caller-ID health | **Built** | Cheap, auto-appliable, graded, P0 for Product | Re-admission after cool-down; proactive load spread |
| C6 | Variant experiments | **Built** | Main lift source | Interaction tests welcome × voice |
| C7 | Promotion, decay, rollback | **Built** | Graded directly; most harm came from here, so most of my time went here | Faster decay detection (§13) |
| C8 | Hallucination response | **Built** | Graded MTTR; constraint on credits | LLM path only lightly exercised |
| C9 | Governance client | **Built** | Every change goes through it | Re-proposing stale approvals smarter (rebase) |
| C10 | Impact / affected / dry run | Partial | Honest formulas, replay of our own counters (§6) | Real replay against historical cohorts |
| C11 | Supervisor view | Partial | `python -m controller.audit view` JSON | UI |
| C12 | Audit store | **Built** | Mandatory; `decisions` + `proposals` + `config_versions` | — |
| C13 | Crash recovery | **Built** + evidence | Non-negotiable | — |
| C14 | Loop observability | Partial | `metrics` table + `audit health` + alert rules | Export to Prometheus |
| C15 | Fair allocation | **Cut** | Credits are per-incident capped with a floor; approver attention is per workflow by policy | Per-tenant credit budgets |

**Principle:** build what a hidden scenario scores and what the non-negotiables require, and make it *safe first*. A harmful change counts against you twice (grader and CTO), so every hour I had left went into removing harmful changes rather than adding capabilities.

## 3. Stakeholders

### 01 — Nikhil Rao, Sales
- **Accepted:** speed where it's safe. Experiments start on D0 in the first approver hour, and caller-ID fixes auto-apply in minutes where policy allows.
- **Declined:** a blended score (breaks Product's definition and README constraint 3). "Live by evening" (a lunch-time lead at ~100 calls per arm is noise: ≥400 connected calls per arm before any look). Rolling out "persuasive" everywhere.
- **Wrong claims:** "Kestrel has auto-apply for everything". False: prompt and cohorts aren't in `allowed_dims`, and `max_shift` is 0.2. "Northwind is fine with auto-apply on KYC". False: `nw_kyc` has auto-apply disabled, and Northwind Compliance requires named approval for anything customer-facing. "Persuasive" (P4) isn't an option on `nw_kyc` at all, and prompt changes need validation evidence.
- **Reply:** "Nikhil, for the summit you'll get a per-client lift on each workflow's own KPI (pickup or engagement), with the audit trail behind it. That is the story a BFSI compliance head buys. I can't blend the KPIs or push winners at lunch: at that point we have ~100 calls per variant, and a coin-flip 'winner' that hurts a cohort is a board conversation for Northwind. Auto-apply is narrower than you were told (Kestrel: caller ID, voice, welcome, small steps only; Northwind KYC: none). 'Persuasive' isn't approved for KYC and needs safety validation elsewhere. Today's numbers: +16% leads concluded on the incident scenario, zero harmful changes."

### 02 — Meera Iyer, Compliance (Northwind)
- **Accepted:** all five conditions. Customer-facing changes always go to approval (even where auto is allowed). Prompt changes carry a `validation_run_id`. "Why did this customer hear X" is answerable from `config_versions` + `proposals` + `decisions` (`audit why`), and every call event carries `config_version`/`variant`. Slow and right: Holm-corrected tests, recency and trend guards, harmed-segment protection. Requests only go out in your approver hours (10:00–19:00, KYC 10:00–18:00), early enough to be decided the same day.
- **Wrong claim:** "timing and caller-ID rotation are covered by the policy we signed". True for renewal, **not for KYC**, where auto-apply is disabled. Every KYC change, operational ones included, goes to your approvers.
- **Reply:** "Meera, agreed on all five. Nothing a customer hears changes without your approver, and script changes carry a validation run ID. For any customer and day we can give the config version, variant, the proposal and its evidence, who approved it and when: one query, minutes, not 24 hours. One correction: on KYC your signed policy doesn't allow auto-apply at all, so caller-ID rotation there also comes to your approvers. Requests only go out inside your approver hours. The weekly summary will list every operational change on renewal with its reason."

### 03 — Kabir Menon, Platform & SRE
- **Accepted:** kill/restart test (`scripts/crash_test.sh`, §9). Idempotency everywhere (§9). Paging rules (§10). No new stateful infra: SQLite is a file inside the process, not a service. Loop health without logs (`audit health`).
- **Pushed back:** none. "No new stateful infra" is honoured, with the caveat that SQLite is single-writer. The production move is Postgres (same schema, same transactions).
- **Reply:** "Kabir, it's one Python process and one SQLite file in WAL mode: nothing new to run at 2 a.m. Every chunk is committed with its cursor in one transaction, and every proposal is written before it's sent, then reconciled against the simulator by ID on restart. The crash test kills it 6–8 times at random; events match the simulator exactly and nothing is applied twice. Load scenario: about 24 s wall per simulated day on a 2-vCPU box (target 10 min), 72k events/s, <1 GB RSS. What breaks first at 10× is the in-memory lead cache. Fix and sharding plan are in §8."

### 04 — Anita Desai, Kestrel Ops Supervisor
- **Accepted:** your edits are never undone. A supervisor edit closes our experiment on that dimension, and we wait a day before testing it again. At most 2 routine requests a day, none before 11:00, one batched request per workflow. Customer-facing changes go to approval even though your policy would let us auto-apply them. One screen: `audit view`. Validation is treated as safety-only, and engagement is checked after every prompt fix (your "verbatim script" warning).
- **Pushed back:** incident fixes (e.g. a hallucinating prompt) may use the policy's full 4/day. In the test, two random rejections on the fix would otherwise have kept a bad prompt live overnight.
- **Reply:** "Anita, we'll never revert your changes. If you edit something we're testing, we stop that test and leave it alone for a day. You'll get at most two routine requests a day, after 11:00, each one batching everything for your line. Anything a customer hears goes to you first, even where your policy would let us auto-apply. One exception: if a prompt starts hallucinating, we may send up to four requests that day to fix it. Validation only proves safety, so after a fix we check customers still stay on the call. Your one screen: what's tested, what's winning, what's waiting for you, what changed today."

### 05 — Tara Kulkarni, Product
- **Accepted:** separate KPIs (primary + guardrail check on every promotion). One cohort object (`cohorts` table, same IDs in config, stats and view). Proposals carry an impact score, diff, affected leads and dry run, and the impact score has a stated meaning (§6). Expired = rejection, re-proposed with fresh data, never resubmitted. Learning only from call events' actual `variant`, so arms that never ran never count. Winners stay inside one workflow.
- **Minimum cohort size / window (your open question):** 400 connected calls per arm before the first look, one look per day, one-sided α=0.015 per look with Holm across arms (≈ Pocock for 5 looks). Cost: at ~55% engagement, a +10% relative lift needs ~1,265 per arm for 80% power. On renewal (~1,100 connected/day, 15% per challenger) that's ~5–8 days. Faster means more false winners.
- **Pushed back:** per-person call time as P0 (data too sparse; per-cohort timing is the honest version and I cut it). The consolidated view is JSON/CLI, not a UI.
- **Reply:** "Tara, KPIs stay separate, cohorts are one object with one ID everywhere, and every proposal carries a meaningful impact score, a diff, affected leads and a dry run. My answer to cohort size: 400 connected calls per arm before deciding, one look a day, Holm-corrected. That's ~5–8 days to call a +10% winner on renewal. Halve it and expect roughly twice the false winners. I said no to per-person call time: people get 2–8 calls each and most never come back, so per-person estimates are noise. Caller-ID health and the supervisor view are built (the view as JSON for now)."

### 06 — Aryamann, CTO
- **Accepted:** explainability over size (every decision is in `decisions` with numbers). Credits only where they change a decision: revert to the last known-good prompt first (3 credits), and the LLM only if there isn't one. Design for the envelope (§8). Choosing (§2). Docs for whoever gets paged (§10, `audit` commands).
- **Caught:** the memo claims listed under Sales and Compliance above.
- **Reply:** "Aryamann, I chose eight capabilities and cut per-person timing, cross-tenant fairness and a UI. Most of my time went into making changes safe: across all three public scenarios the controller applied 62 changes, none harmful by the grader's truth. The first versions had up to six harmful changes, almost all from false winners and false rollbacks, and §5 says how each was removed. Credits: 3 spent on the incident scenario. At 10×, the in-memory lead cache breaks first; then partition by tenant."

## 4. Architecture
```
              ┌──────────────── simulator (HTTP) ────────────────┐
              │ /events/chunks  /workflows/*/config  /approvals  │
              └──▲──────────┬─────────────▲──────────────▲───────┘
   advance 30m   │          │ chunks      │ GET config   │ POST/GET approvals, apply, PUT config
                 │          ▼             │              │
            ┌────┴───┐ ┌──────────┐ ┌─────┴──────────────┴────┐
            │ main   │ │ Ingestor │ │ Governance (state m/c)  │◀── intents ──┐
            │ loop   │ │ chunk →  │ │ batching, hours, budget,│              │
            └────────┘ │ counters │ │ auto vs approval, apply │     ┌────────┴────────┐
                       └────┬─────┘ └───────────┬─────────────┘     │ Brain (policies)│
                            │ 1 tx per chunk    │ intent row first  │ supervisor edits│
                            ▼                   ▼                   │ hallucination   │
   ┌──────────────── SQLite (WAL) — the only state ───────────────┐ │ caller-ID health│
   │ chunks(cursor) leads agg(wf,day,hour,key) config_versions    │◀┤ experiments     │
   │ cohorts experiments proposals decisions(audit) metrics meta  │ └─────────────────┘
   └──────────────────────────────────────────────────────────────┘
         ▲ read-only: python -m controller.audit why|view|health|log
```
Each tick: ingest new chunks → refresh configs → handle supervisor edits → reconcile open proposals (poll, apply) → policies produce intents → plan (auto-apply one step, or batch into one approval) → metrics → advance 30 min.

**On restart:** the store is reopened (a different world signature archives it). Chunks after the cursor are re-ingested. `intent` proposals are looked up by ID in the simulator (adopted, resent at the same sim minute, or dropped), and approved ones are applied or marked stale. Policies are state-driven, so they recompute the same intents.

## 5. The learning loop
- **Cohorts.** Start with `default` only. A cohort is created in exactly two situations, both at a daily look: (a) **segment winner**: no overall winner, but within one feature value (e.g. `lang=hi`) a challenger beats control with Holm over every (segment × challenger) test, ≥200 connected per arm, and it's still ahead in the last 48h. (b) **harmed segment**: at promotion, a segment where the winner is significantly worse keeps the control. Max 4 cohorts per workflow. New cohorts are appended, so earlier ones keep their members. Segment stats use default-cohort calls only, so a cohort can't contaminate the next test. That was a real bug that caused harm on the load scenario.
- **Experiment design.** Challengers share 30% of a dimension (control 70%), with up to 3 challengers. The simulator samples welcome and voice independently, so both run at once and are analysed marginally (a factorial design for free). Options our own data already shows are worse than control (z<−1, n≥300) aren't re-tested, and losers are retired for 7 days. Fixed splits rather than bandits: allocations can only move through approvals (2–4 per day), so adaptive allocation isn't really available, and fixed splits keep the test valid.
- **Deciding a winner.** One look per day at the start of approver hours (no peeking every tick). Two-proportion z vs control, one-sided, Holm across arms at α=0.015. Plus: (1) still ahead in the last 48h (z≥1.28), (2) **trend guard**: last-24h lift ≥ half the all-time lift, (3) guardrail KPI not significantly worse. Losers (worse overall, or worse in the last 48h) are pruned. If every challenger loses, the test closes. With no winner the test keeps running. I removed "close after N days", because snapping back to control when challengers look slightly better was itself harmful.
- **False-winner rate.** ≈5% family-wise per test with ≤5 looks. The guards make it lower at the cost of about a day's delay. Sample sizes at 55% base: +10% relative needs 1,265 per arm, +15% needs 557, +5% needs 5,104 (`stats.n_per_arm`).
- **Decay and rollback.** On promotion, 15% stays on the old control as a **holdout**. Decay = the winner's lead over the holdout (same hours, so general drift cancels) has dropped significantly (z<−3.0) or the winner is behind (z<−2.58), and the lead is ≤0. It's checked every 6 h and must hold on **two consecutive checks**. The window is 24h, widened to 48h if the holdout has <150 connected calls. Earlier versions compared the winner to its own past and fired on a workflow-wide dip. That was the main source of harmful rollbacks.
- **Call time and caller ID.** Call time: cut (§2). Caller ID: per-DID pickup over 3h vs pooled peers (z≤−3.5 and <70% of peers, ≥120 dials), or vs its own history when it's the only DID. Quarantined DIDs are removed. Auto-apply where policy allows, stepped by `max_shift`. On pickup-primary workflows caller ID is also the experiment dimension, with promotion capped at 60%.
- **Guardrail.** A winner is blocked if its guardrail KPI is worse (z<−2.33 and more than half the allowed drop). Example: on renewal, a welcome winner whose pickup fell 1+ point vs control would not be promoted.

## 6. Governance
- **State machine:** `intent → pending → approved → applying → applied`, plus `rejected`, `expired`, `lapsed`, `stale`, `failed`; auto is `intent → applied | failed | stale` (`governance.py` docstring). Expired, rejected and stale are never resubmitted. Policies recompute against the current config and a new proposal (new ID, fresh numbers) is made. Routine re-proposals wait 3h after a rejection.
- **Timing and batching:** one routine approval in flight per workflow, batching everything. Sent only between approver start (Kestrel: 11:00) and *end − min(worst-case latency, 4h)* (urgent: end − 30 min), so it's normally decided the same day. Budget: routine work leaves one of the 24h slots free for incidents. Kestrel routine is capped at 2/day, and incident fixes may use the policy maximum. Urgent requests go alone, so a judgement-call rejection on routine work can't block a fix. Approved changes are applied on the next tick (≤30 sim-min, well inside the 2h window). Result: 0 lapsed, 0 expired, 0 apply conflicts in every run.
- **Auto-apply:** only for operational dims (caller ID, schedule), within `allowed_dims` and `max_shift`. I voluntarily don't auto-apply welcome/voice on Kestrel even though policy permits it (Anita, Meera's principle, CTO). The cost is a slower ramp; the benefit is that a human sees every customer-facing change.
- **Impact score** = expected relative lift on the primary KPI × share of traffic moved ÷ 10%, clipped to [0,1]. So 1.0 means "≥10% relative lift on the workflow". Exploration starts score 0.05, because nothing is expected yet. Incidents: excess hallucination rate ÷ 2 points. **Affected leads** = a day's batch × the largest traffic share whose experience changes (cohort-weighted). **Dry run** = replay against our own counters: per-arm rates and CIs, the expected workflow rate before and after, history baselines, and the worst case for exploration. It's honest but it isn't a counterfactual replay, and it says so.
- **Supervisor edits mid-experiment:** logged as `supervisor_edit`. Experiments on that dimension close, with a 1-day cool-down. Any approval based on the old version is refused at apply time as stale and re-planned. The prompt watch lowers the hallucination bar after a supervisor prompt change.

## 7. Incidents
- **Detection:** hallucination flags on connected calls since the current prompt went live, over the last 6h. Fires if rate ≥3× the history baseline, ≥120 connected, and Poisson tail p ≤ 1e−7 (≤1e−4 within 12h of a prompt change, since a change is a strong prior). The first version used a normal-approximation z≥4. It fired a false incident on KYC, which is why I switched to an exact tail with a much smaller p. With ~1,500 overlapping checks per run, p=1e−7 keeps the expected false alarms well under 1.
- **Picking a fix:** first, a prompt we've run with a normal rate (≥1,000 connected) → validate it (n=300, 3 credits). Otherwise one LLM call (3 credits) → validate the candidates in order. Caps: 15 credits per incident, never below a 10-credit floor.
- **Verify:** after apply, ≥200 connected on the new prompt; check the hallucination rate is back near baseline and engagement isn't below baseline (z>−3), because validation says nothing about engagement.
- **public_02 timeline (ks_cancel):** D3 12:00 supervisor ships P2 (`supervisor_edit` logged, not reverted) → **D3 13:00 incident opened** (11/158 = 7.0% vs 1.5%, p=3.2e−5) → P1 validated 98.7% (3 credits) → proposal sent D3 13:00 → approved and applied **D3 14:30** → verified D3 18:00. Grader MTTR: 180 min. Credits: 3 of 200. Caller ID: D2 flagged D2 12:00 and auto-rotated in 3 steps (max_shift 0.2); grader share 14% on the flag day, then 0%.

## 8. Scale (public_03_load, measured on a 2-vCPU / 7.7 GB sandbox, smaller than the target box)
| metric | value |
|---|---|
| history catch-up | 5.54M events in 73 s (~76k ev/s) |
| ingest throughput | ~72k events/s steady |
| wall time per simulated day | **~24 s** (≈7 s simulator advance, ≈11 s ingest, ≈4 s decisions); target was 10 min |
| decision lag | ≤1 tick (30 sim-min); ~0.5 s wall per tick |
| peak RSS | 990 MB (grows ~54 MB/sim-day: lead cache) |
| store size | 191 MB after 12 sim-days (5.5M history + 4.2M live events) |

(`reports/public_03_loop_health.txt`, `reports/public_03.md`.)

**What breaks first at 10×** (8.4M events/day, ~23M leads): the **in-memory lead cache** (~10 GB). Fix: keep only leads from campaigns still inside their cadence (≤3 days) in memory and fall back to SQLite. Next: ingest at ~2 min per sim-day is fine, but one process serially handling ~1,000 workflows × 3 GETs per tick is ~3k calls per tick. **Partitioning:** shard by tenant (approver, policy and credits are per tenant/workflow, so nothing is shared), one controller process per shard with its own store (or a Postgres schema per shard). The only global resource is credits → a per-tenant credit budget (which is C15).

## 9. Reliability
- **Method:** `scripts/crash_test.sh 8` runs public_02, `kill -9`s the controller 6–8 times at random wall-times (including during history catch-up and during approver hours), restarts it each time, then `scripts/check_consistency.py` compares the store with the API.
- **Result** (`reports/crash_test.log`): calls per workflow equal the simulator exactly (84,795 / 113,056 / 47,199). No approval applied twice, none approved-but-forgotten, none lapsed. Store status matches the simulator for every approval. Graded run: +15.8%, 18 changes, 0 harmful. **State lost:** none. Known gap: if killed between a validation call and saving its result, the validation is repeated (≤3 credits).
- **Idempotency keys:** chunk number (cursor in the same transaction). `proposal_id` is deterministic (`prefix-wf-simminute-hash(intent keys)`), written as `intent` before the call. On restart at the same sim minute the identical request is resent with the same ID; if time has moved on it's dropped and re-planned. `approval_id` is reconciled via `GET /approvals`. Apply is guarded by checking the simulator's status (`applied`) and `config/history`. On-applied callbacks are idempotent (`UPDATE … WHERE status='planned'`).
- **Simulator errors:** transport errors and 5xx are retried with backoff (8 attempts). 4xx is information: 409 stale → mark stale and re-plan, 409 duplicate → reconcile, 410 → lapsed, 403 auto → recorded, 402 → credit floor stops spending first.

## 10. Audit & observability
`python -m controller.audit why --db state/run_02.db --wf ks_cancel --at "D3 16:00"` (real output, `reports/why_example.txt`):
```
ks_cancel at D3 16:00 was running config v7, applied D3 14:30 by controller_approved; changed ["prompt_version"]
  proposal prop-ks_cancel-5100-9ea59a35 (approval), created D3 13:00: Fix hallucination incident: switch prompt P2 → P1
  why: Hallucination flags on P2 are 7.0% of connected calls vs a 1.5% baseline (z=5.7, n=158). P1 passed
       validation at 98.7% (n=300). We will check engagement after the switch, since validation measures safety only.
  evidence: {"validation_run_id": "val_00001"}  impact_score=1.0 affected_leads=1500
    D3 13:00  proposal_sent      Fix hallucination incident: switch prompt P2 → P1
    D3 14:30  approval_approved  apr_00005 approved
    D3 14:30  applied            config v7 applied (approval)
  approved by: the ks_cancel client approver via apr_00005 (simulated human; the API gives no name)
  before (24h): {'dials': 4800, 'pickup': 0.2288, 'engagement': 0.4627, 'halluc_rate': 0.0264}
  after  (24h): {'dials': 4800, 'pickup': 0.214, 'engagement': 0.5005, 'halluc_rate': 0.0185}
  next change: v8 by controller_auto at D4 17:00 ["caller_id"]
```
Other commands: `audit view` (supervisor screen; `reports/supervisor_view_ks_cancel.json`), `audit health` (per-day events, ingest rate, decide time, decisions, credits, RSS), `audit log --kind did_flagged`.

**Page** (rules; `audit health` currently computes only the approved-but-unapplied one): no tick progress for 15 wall-min. An approved proposal unapplied for 90 min (it will lapse). Credits below the floor with an incident open. An incident open >6 sim-h with no proposal sent. Every caller ID for a workflow quarantined.
**Don't page (morning report):** routine rejection or expiry, a test with no winner, one caller ID quarantined and rotated, stale re-proposals.

## 11. Results
**public_01** (`reports/public_01.md`)
| workflow | conclusion | Δ | pickup | Δ | engagement | Δ |
|---|---|---|---|---|---|---|
| ks_cancel | 0.351 | +2.7% | 0.245 | +2.3% | 0.502 | +0.3% |
| nw_kyc | 0.469 | +24.4% | 0.303 | +25.3% | 0.593 | −3.2% |
| nw_renewal | 0.410 | −2.4% | 0.261 | −0.4% | 0.538 | −1.6% |
| ALL | 0.396 | +5.4% | 0.262 | +5.6% | 0.535 | −0.7% |
7 applied: 5 beneficial, 2 neutral, **0 harmful**. 0 credits.

**public_02** (`reports/public_02.md`)
| workflow | conclusion | Δ | pickup | Δ | engagement | Δ |
|---|---|---|---|---|---|---|
| ks_cancel | 0.320 | +31.3% | 0.221 | +20.8% | 0.498 | +5.6% |
| nw_kyc | 0.466 | +21.3% | 0.285 | +15.0% | 0.618 | +3.0% |
| nw_renewal | 0.433 | +0.8% | 0.263 | −0.1% | 0.552 | +0.9% |
| ALL | 0.390 | +16.2% | 0.248 | +11.2% | 0.545 | +2.9% |
18 applied: 15 beneficial, 3 neutral, **0 harmful**. 0 lapsed/expired/conflicts. 3 credits.

**public_03:** +16.3% conclusion overall, 37 applied (29 beneficial, 8 neutral, 0 harmful).

**Interpretation.**
- KYC gains come from caller-ID work. Spreading load off a single, degrading number is the biggest single lever in these worlds.
- The Kestrel cancel line in public_02 gains from the fast prompt fix plus caller-ID rotation.
- **Where I'm weak:** renewal in public_01 (−2.4% outcome). W3 won early, was promoted on D4, then faded. My conservative decay rule (two consecutive 6-hourly checks, thin holdout) hadn't rolled it back by D8. On public_02 the same rule did remove W3 by D7. The KYC engagement guardrail moved −3.2% relative in public_01, which is about −1.9 points absolute: inside `engagement_rate_max_drop: 0.02` if that is absolute (my assumption), a breach if it is relative. It comes from the pickup gain (more marginal people now pick up), not from any change to what they hear.
- **Earlier versions were harmful** (up to 6 harmful changes on load). Causes, all fixed and committed: rollback on a shrinking-but-positive lead; self-comparison confounded by drift; segment stats contaminated by existing cohorts; re-testing retired losers; closing tests back to a worse control.

## 12. Trade-offs & rejected alternatives
| Option | Why considered | Why rejected / what instead |
|---|---|---|
| Thompson sampling | Faster exploitation | Allocations only change via approvals (2–4/day) or ±0.2 steps; adaptive allocation is not available. Bandit posteriors also aren't the "deterministic winner selection" the constraints ask for |
| Store raw call events | Full replay | ~25M rows per run for no decision value; counters per (wf, day, hour, key) answer everything the loop asks |
| Postgres now | Production target | Adds a service to run for the assignment; same schema/transactions port directly |
| Decay = winner vs its own past | More power than the thin holdout | Confounded by workflow-wide drift; caused false rollbacks. Lead over a 15% holdout instead |
| Close tests after N days | Bounded exposure | Snapping back to control was harmful when challengers were mildly better; tests now run until a decision |
| Auto-apply voice/welcome on Kestrel | Policy allows it, faster | Customer-facing; supervisor and compliance asked for a human in the loop |
| LLM first for incidents | Simple | Reverting to a known-good prompt is cheaper and more credible; LLM only if none exists |

## 13. Known weaknesses
- **Decay detection is slow** when the holdout is thin (low-pickup workflows): ~2–4 days. I chose it over false rollbacks. A better test (CUSUM on the lead, or a larger holdout early after promotion) is the next thing to do.
- **Crash runs are consistent but not bit-identical** to an uninterrupted run (+15.8% vs +16.2% on public_02). Decisions match up to D3, and I didn't find the source of the divergence in time. Correctness checks all pass.
- Quarantined caller IDs never come back. Reputation recovers in reality, and a workflow can run out of numbers (that should page).
- Segment search uses single features only, and up to 4 cohorts.
- The dry run is a replay of our own counters, not a counterfactual simulation.
- Interaction effects (welcome × voice) aren't tested, only marginal effects.
- One process, serial over workflows; the lead cache grows with every campaign.
- No per-tenant credit budget (C15).

## 14. If this went to production at Formi next month
1. Shadow mode on two real workflows: compute every intent, send nothing, and compare decisions with what humans did.
2. Move the store to Postgres (same schema) and add the lead-cache window. Wire `metrics` to Prometheus and the paging rules to on-call.
3. Named approvers, and a weekly operational-change summary for Compliance (Meera's condition 1).
4. Replace the decay rule with a CUSUM on the lead over the holdout, then calibrate the false-alarm rate on replayed history.
5. Caller-ID re-admission with a cool-down and a small probe share.
6. Per-cohort call-time weights (C4), proposed in batches with cohort changes.
7. Shard by tenant, with per-tenant credit budgets (C15).

## Running it
```bash
pip install -r requirements.txt
python -m sim serve --scenario scenarios/public_02_incidents.yaml --run-dir runs/mine02 &
./run.sh http://127.0.0.1:8700                 # state in state/<scenario>.db; re-run resumes
scripts/run_scenario.sh scenarios/public_01_dev.yaml 01      # baseline + sim + controller + grade
scripts/crash_test.sh 8                                       # kill/restart evidence
python -m controller.audit view --db state/run_02.db          # supervisor screen
python -m pytest -q tests
```
Code map: `controller/main.py` (loop), `ingest.py` (C1), `governance.py` (C9), `policies.py` (C2/C5–C8/C10), `stats.py`, `store.py` (schema), `audit.py` (C11/C12/C14). Tunables are at the top of `policies.py`, each with a comment saying why.
