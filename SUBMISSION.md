# Outcome-First Agent Loop — Submission

**Name:** Tanya · **Date:** 2026-11-07 · **Hours actually spent:** 7 hours, AI-assisted (every line reviewed) · **Language / storage:** Python 3.11+, httpx, SQLite (WAL, one file)

---

## 0. TL;DR
- One process: event chunks → counters in SQLite → four state-driven policies (supervisor edits, hallucination, caller-ID health, experiments) → one governance client that every change goes through.
- **Five capabilities done deeply** (C6+C7 experiment lifecycle, C8, C5, C2) on top of the **four the constraints force** (C1, C9, C12, C13, built as one crash-safe design). C3, C10, C11, C14 are thin by-products. **C4 and C15 are cut**, with numbers (§2).
- **public_01: +5.4% leads concluded, 7 changes, 0 harmful. public_02: +16.2%, 18 changes, 0 harmful, bad prompt detected in 1h and fixed in 180 min for 3 credits. public_03 (load): +16.3%, 37 changes, 0 harmful, ~24 s wall per simulated day.**
- Crash test: 6–8 random `kill -9`s; every event counted once, nothing applied twice, nothing lost or lapsed.
- Biggest known weakness: rollback of a fading winner is deliberately slow (§13).

## 1. Assumptions
1. `engagement_rate_max_drop: 0.02` / `pickup_rate_max_drop: 0.02` are absolute (percentage points).
2. The approver's identity isn't exposed by the API, so "who approved" = the workflow's client approver + `approval_id` + timestamps. In production this would be a named user.
3. Engagement levers are welcome message and voice; pickup levers are caller ID (and schedule). Engagement-primary workflows test welcome/voice; pickup-primary workflows test caller ID. Welcome/voice aren't tested on pickup-primary workflows (no effect on their primary KPI, and it would spend their 2/day approval budget).
4. "Customer-facing" = welcome, voice, prompt, cohorts. Even where policy allows auto-applying them (Kestrel), I send them for approval (§6).
5. A caller ID whose pickup collapses relative to its peers over a 3-hour population is bad. Quarantine is permanent for the run (§13).
6. Spam flagging is driven by volume per number (standard dialler practice). So when caller ID is the lever, the "winner" gets at most 60% and the rest is spread.
7. The supervisor memos describe real client preferences, encoded as stricter-than-policy limits (`CLIENT_PREFS` in `governance.py`), keyed by tenant. Hidden scenarios with other tenants just get their policy.
8. One prompt per workflow, so prompts aren't A/B tested. A prompt only changes to fix an incident, with validation evidence.
9. History (pre-D0) ran on the default config, so it gives baselines (hallucination rate, per-DID pickup, KPI levels), not variant rankings.
10. A lead is only dialled within its cadence (3 attempts), so its features are only needed for a few days after its `lead` event (used in the 10× fix, §8).

## 2. Scope decisions
**How to read this:** the brief asks for five capabilities done properly, not fifteen sketched. Four capabilities aren't really a choice, because the constraints require them. I built those as one design, then chose five to do deeply. Everything else is either a by-product of those, or cut.

### Tier 1: required by the constraints (built as one design)
| # | Capability | Status | Why it isn't optional | What it would take to finish |
|---|---|---|---|---|
| C1 | Ingestion | **Built** | Nothing can be learned without it; backlog-safe and restartable is part of constraint 8 | Windowed lead cache + `hour_abs` index for long runs and 10× (§8) |
| C9 | Governance client | **Built** | Constraint 2: nothing changes outside it | Rebase a stale approval instead of re-proposing |
| C12 | Audit store | **Built** | Mandatory floor | Retention policy, Compliance read replica |
| C13 | Crash recovery | **Built** + evidence | Constraint 8, non-negotiable | Bit-identical replay after a crash (§13) |

C1 and C13 are one mechanism: each chunk's counters commit in the same transaction as its cursor, and every proposal is written before it's sent. C12 is the same store, read by `audit why`.

### Tier 2: chosen and done deeply (the five)
| # | Capability | Why chosen | Evidence it's done properly | What's still missing |
|---|---|---|---|---|
| C6+C7 | Experiments, promotion, decay, rollback | All the lift comes from here, and "harmful changes" and "decay" are graded directly | Min sample sizes, Holm, recency + trend guards, 15% holdout. 0 harmful in 62 changes | Rollback is slow; no completed rollback in the final runs (§13) |
| C8 | Hallucination response | Graded on time-to-fix; the scenario's headline incident | Detected 1h after the bad prompt, fixed in 180 min, verified after apply, 3 credits | LLM path not exercised in the final runs (known-good prompt was always available) |
| C5 | Caller-ID health | Cheap, auto-appliable, graded, P0 for Product | D2 flagged at z=−4.4, rotated in 3 `max_shift` steps, 0% share from the next day | No re-admission; exploration of new numbers only on pickup-primary workflows |
| C2 | Shared cohort object | Product asked for it; the real effects depend on the segment | One table, one ID in config, stats and view. Same cohorts found independently on 12 workflows (V3 for 60+, V4 for 31–45, W2 for tier-1 cities) | Single-feature segments, max 4 per workflow |

### Tier 3: thin by-products (honest depth, not sketches)
| # | Capability | Status | Why thin is the right depth | What it would take to finish |
|---|---|---|---|---|
| C3 | Bootstrap from history | Partial | History ran only on the default config, so it can't rank a single variant. Baselines are the only honest use (~30 lines on top of C1) | — |
| C10 | Impact / affected / dry run | Partial | Required on every proposal, so it exists with stated formulas (§6). A true "replay against historical cohorts" is impossible for variants that never ran | Counterfactual replay once there's variant history |
| C11 | Supervisor view | Partial | One JSON command over the C12 store; a UI adds nothing graded | Small web page over the same query |
| C14 | Loop observability | Partial | `metrics` row per tick + `audit health`; paging rules written, one computed | Prometheus export + the remaining alert rules |

### Cut
**C4: call-time optimisation.**
- **Per person: cut firmly.** Each lead gets 3 attempts (cadence `[2, 3, 3]`) and only 20–40% are returning people (`returning_share` 0.2–0.4). For most people that's 3–4 yes/no outcomes across 12 calling hours, too few to estimate a best hour. A per-person model would mostly fit noise.
- **Per cohort: cut on priority, though the opportunity is real.** Measured from history: pickup varies 21–31% by hour, and re-timing calls by age band could lift pickup by **at most ~8–9% relative** on each workflow (nw_kyc +8.0%, nw_renewal +8.4%, ks_cancel +8.8%).
  - That number is a ceiling. Choosing each group's best hours from noisy data inflates it, and hourly dial capacity is fixed, so moving one group into a good hour pushes another out.
  - It needs a `cohorts` change, which needs approval. On KYC (2 requests/day) that budget went to caller-ID work, which delivered **+21–25% pickup**.
  - Pickup is only the guardrail on 2 of the 3 workflows.
  - It is the first thing I'd add next (§14).

**C15: fair allocation across tenants.**
- No scarcity to allocate: credits used were **3 of 200** in public_02 and 0 in public_01.
- Approver attention is already per workflow (own approver, own request limit), so tenants don't compete in the simulator.
- Instead: a 15-credit cap per incident and a 10-credit reserve floor, so one incident can't drain the pool.
- It matters in production with tens of tenants sharing a validation budget: per-tenant credit budgets (§8).

**The principle.** Build what the constraints require, then what a hidden scenario scores, and make it **safe first**. A harmful change counts against you twice (grader and CTO), so once the core worked, every remaining hour went into removing harmful changes, not adding capabilities. The early versions had up to 6 harmful changes; the final one has none across 62 (§11).

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
- **Pushed back:** per-person call time as P0 (3 attempts per lead, 20–40% returning: too sparse). Per-cohort timing is the honest version; I measured its ceiling (≤ ~8% relative pickup) and cut it on priority (§2). The consolidated view is JSON/CLI, not a UI.
- **Reply:** "Tara, KPIs stay separate, cohorts are one object with one ID everywhere, and every proposal carries a meaningful impact score, a diff, affected leads and a dry run. My answer to cohort size: 400 connected calls per arm before deciding, one look a day, Holm-corrected. That's ~5–8 days to call a +10% winner on renewal. Halve it and expect roughly twice the false winners. I said no to per-person call time: each lead gets 3 attempts and only 20–40% ever come back, so per-person estimates are noise. Per-cohort timing is worth up to ~8% pickup on paper; it's my first addition next. Caller-ID health and the supervisor view are built (the view as JSON)."

### 06 — Aryamann, CTO
- **Accepted:** explainability over size (every decision is in `decisions` with numbers). Credits only where they change a decision: revert to the last known-good prompt first (3 credits), and the LLM only if there isn't one. Design for the envelope (§8). Choosing (§2). Docs for whoever gets paged (§10, `audit` commands).
- **Caught:** the memo claims listed under Sales and Compliance above.
- **Reply:** "Aryamann, four things were forced by the constraints (ingestion, governance, audit, crash safety) and built as one design. On top I chose five and went deep: experiments with promotion and rollback, hallucination response, caller-ID health and one cohort object. Call timing and cross-tenant fairness are cut, with numbers. Across the three public scenarios: 62 changes applied, none harmful by the grader's truth. Early versions had up to six; §11 lists each cause and fix. 3 credits spent. At 10×, memory breaks first (lead cache), not throughput."

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
- **Cohorts.** Start with `default` only. A cohort is created in exactly two situations, both at a daily look:
  - **Segment winner:** no overall winner, but within one feature value (e.g. `age_band=60+`) a challenger beats control. That needs Holm over every (segment × challenger) test, ≥200 connected per arm, and still being ahead in the last 48h. Real example: `60+ → voice V3, 278/370 vs 1658/2551, Holm over 39 tests`.
  - **Harmed segment:** at promotion, a segment where the winner is significantly worse keeps the control.

  Minimum 200 connected calls per arm per segment, max 4 cohorts per workflow, single features only: all to avoid splitting traffic too thin to conclude anything. New cohorts are appended, so earlier ones keep their members. Segment stats use default-cohort calls only, so a cohort can't contaminate the next test (a real bug that caused harm on the load scenario).
- **Experiment design.** Challengers share 30% of a dimension (control 70%), with up to 3 challengers.
  - The simulator samples welcome and voice independently, so both run at once and are analysed marginally (a factorial design for free). Interactions aren't tested (§13).
  - Options our own data already shows are worse than control (z<−1, n≥300) aren't re-tested, and losers are retired for 7 days.
  - Fixed splits, not bandits: allocations only move through approvals (2–4 per day), so adaptive allocation isn't really available, and fixed splits keep the test valid.
- **Deciding a winner.** One look per day at the start of approver hours (no peeking every tick). Two-proportion z vs control, one-sided, Holm across arms at α=0.015 (≈ Pocock level for 5 looks). A winner also needs:
  1. to still be ahead over the last 48h (z≥1.28)
  2. a **trend guard**: last-24h lift ≥ half the all-time lift
  3. a guardrail KPI that isn't significantly worse

  Losers (worse overall, or worse in the last 48h) are pruned. If every challenger loses, the test closes. With no winner it keeps running: "close after N days" was removed because snapping back to a worse control was itself harmful.
- **False-winner rate.** ≈5% family-wise per test with ≤5 looks; the guards push it lower at the cost of about a day's delay. Sample sizes at a 55% base: +10% relative needs 1,265 per arm, +15% needs 557, +5% needs 5,104 (`stats.n_per_arm`).
- **Decay and rollback.** On promotion, 15% stays on the old control as a **holdout**. Decay = the winner's lead over the holdout (same hours, so general drift cancels out) has dropped significantly (z<−3.0) or the winner is now behind (z<−2.58), *and* the lead is ≤0. It's checked every 6h and must hold on **two consecutive checks**. The window is 24h, widened to 48h if the holdout has <150 connected calls. Earlier versions compared the winner to its own past and fired on a workflow-wide dip; that was the main source of harmful rollbacks. A fading arm *before* promotion is caught by the 48h loser test. That's how the decaying W3 was removed in public_02 (D7: z=−2.59 over 48h while level overall).
- **Call time and caller ID.**
  - Call time: cut, with the measured ceiling (§2).
  - Caller ID: per-number pickup over 3h vs pooled peers (z≤−3.5, <70% of peers, ≥120 dials), or vs its own history when it's the only number. Quarantined numbers are removed, auto-applied where policy allows in `max_shift` steps.
  - On pickup-primary workflows, caller ID is also the experiment dimension: new numbers are explored at 15% each with the same tests, and promotion is capped at 60%.
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

## 8. Scale
Measured on public_03_load with a 2-vCPU / 7.7 GB sandbox (smaller than the target box). The scenario matches the production target: **6.48 lakh dials/day and a 54,000-dial peak hour** (target: ~6.5 lakh/day, >50k/hour), 12 workflows.

| Metric | Measured | Note |
|---|---|---|
| Ingest throughput | **~70k events/s** steady, 76k/s on the 5.5M-event history catch-up | |
| Real arrival rate at peak | ~15–20 events/s (54k dials/hour) | ~3,500× headroom |
| Time per tick (ingest + decide) | avg **0.57 s**, max **1.66 s** (a 192k-event chunk) | |
| Decide time | avg **0.10 s** per tick for 12 workflows (~8 ms per workflow) | |
| Decision lag | ≤ **30 sim-min + ~1 s**: an event affects decisions at the next tick | Tick size is our choice (min 15) |
| Wall time per simulated day | **~24 s** (≈7 s of it is the simulator itself) | Target: 10 min |
| Peak memory | **990 MB**, growing ~54 MB per sim-day | Almost all of it is the lead cache (2.3M leads) |
| Store | 200 MB, 110k counter rows (19 days incl. history) | Counters, not raw events |

(`reports/public_03_loop_health.txt`, `reports/public_03.md`)

**Freshness.** Our reaction time is set by statistics, not ingestion. A hallucination alarm needs ≥120 answered calls (~1h on a 300-dial/hour workflow); a caller-ID alarm needs a 3h window. Cutting ingestion lag from minutes to seconds would save under a minute on a detection that needs an hour of data. In production I'd read micro-batches every ~5–10 s (event → counted in <60 s), run safety checks per workflow when new data lands, and run experiment looks once a day per workflow.

**What breaks first at 10×** (~65 lakh dials/day, ~200 events/s in the calling window, or thousands of workflows):
1. **Memory: the lead cache. This breaks even at 1×, just slowly.** Every lead ever seen stays in memory: ~4.6 lakh new leads/day ≈ +200 MB/day at 1×, so an 8 GB box runs out in ~5–6 weeks; at 10×, in ~4 days. Fix: keep only leads still inside their cadence window (~3 days) and look older ones up in the store. That gives flat memory (~600 MB at 1×). Better: the platform puts the four features on the call event, and the cache disappears.
2. **Counter queries.** ~87 keys per workflow-hour → ~5 lakh rows/day at 500 workflows. Queries filter on a calculated value (`day*24+hour`) with `key` last in the primary key, so they scan a workflow's rows: fine at 110k rows, slow at crores. Fix: an `hour_abs` column indexed as `(wf, key, hour_abs)`, day partitions, hourly rows kept 30 days then rolled up to daily.
3. **One serial loop.** ~8 ms + ~3 API calls per workflow per tick: 500 workflows ≈ 4 s and 1,500 calls per tick. That fits a 30-min tick but not a 1–5 min safety cadence, and one crash pauses everyone.
4. **SQLite's single writer**, only if you skip the next step.

**Not a problem at 10×:** ingest (200 vs 70,000 events/s); governance (limits are per workflow); statistics (10× the calls means tests finish ~10× sooner).

**Partitioning.** Shard by tenant. Tenants share nothing: own policy, objective, approver and limits.
- Each shard is owned by one worker holding a lease, so only one writer exists per workflow.
- Workers read a tenant-partitioned event stream and save the stream offset in the same transaction as the counters (today's chunk-cursor trick, which gives an exactly-once effect).
- State moves to Postgres with the same schema; raw events stay in the platform's data lake.
- The only shared resource is credits → per-tenant budgets (C15).

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
- **Rollback is slow, and none completed in the final runs.** It's strict on purpose: the eager version caused harmful rollbacks. In public_01, W3's lead fell to −9.1% on D6 and the rollback was waiting for its second check when the run ended (renewal finished −2.4%). In public_02 the fading W3 was pruned before it could be promoted. Next: a CUSUM on the lead, or a larger holdout just after promotion.
- **The LLM step of C8 isn't exercised in the final runs** (0 calls). Reverting to a prompt that already ran safely was always possible and cheaper. The LLM path ran only in an earlier version (it suggested P3, which passed validation and was applied).
- **Results vary slightly across machines.** Same machine and Python version: identical every run. On a Mac with Python 3.12, public_01 gave +5.2% and 8 changes (vs +5.4% and 7 here), still 0 harmful.
- **Crash runs are consistent but not bit-identical** to an uninterrupted run (+15.8% vs +16.2% on public_02). Decisions match up to D3; I didn't find the source in time. All correctness checks pass.
- **Caller-ID quarantine is permanent**, and new numbers are only explored on pickup-primary workflows. A workflow can run out of numbers; that should page.
- **No workflow-level KPI-drift alarm.** We detect three causes (bad number, hallucinating prompt, fading winner); a drop with another cause is only visible in `audit health`.
- Segments are single-feature, max 4 per workflow; welcome × voice interactions aren't tested.
- The dry run replays our own counters; it isn't a counterfactual simulation.
- The lead cache grows without limit and counter queries don't use a proper index: fine for the scenarios, not for weeks of production (§8).
- Dead code to remove: `util.day_hour`, `store.now_wall`.

## 14. If this went to production at Formi next month
1. **Shadow mode** on two real workflows: compute every intent, send nothing, and compare with what humans did.
2. **Postgres** (same schema), the windowed lead cache and the `hour_abs` index. Wire `metrics` to Prometheus and the paging rules to on-call.
3. **Named approvers**, and a weekly operational-change summary for Compliance (Meera's condition 1).
4. **CUSUM decay rule** on the lead over the holdout, calibrated for false alarms on replayed history.
5. **Per-cohort call-time weights (C4)**, batched with cohort proposals: the cut with the largest measured upside.
6. **Caller-ID re-admission** with a cool-down and a small probe share; a workflow-level KPI-drift alarm.
7. **Shard by tenant**, with per-tenant credit budgets (C15).

## Running it
```bash
pip install -r requirements.txt
python -m sim serve --scenario scenarios/public_02_incidents.yaml --run-dir runs/mine02 &
./run.sh http://127.0.0.1:8700                 # state in state/<scenario>.db; re-run resumes
scripts/run_scenario.sh scenarios/public_01_dev.yaml 01      # baseline + sim + controller + grade
scripts/crash_test.sh 8                                       # kill/restart evidence
python -m controller.audit why --db state/run_02.db --wf ks_cancel --at "D3 16:00"
python -m controller.audit view --db state/run_02.db          # supervisor screen
python -m pytest -q tests
```
Code map: `controller/main.py` (loop), `ingest.py` (C1), `governance.py` (C9), `policies.py` (C2, C5–C8, C10), `stats.py`, `store.py` (schema, C12/C13), `audit.py` (C11, C12, C14). Tunables are at the top of `policies.py`, each with a comment saying why.
