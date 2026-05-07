# PulseWise Roadmap V2 — Strategic Direction

**For:** Maneesh (WorldWise LLC)
**Authored by:** Strategist role
**Date:** April 30, 2026
**Status:** Replaces the implicit roadmap embedded in `PULSEWISE_ERD_ENGINE_HANDOFF.md` and `PULSEWISE_ANALYTICS_DASHBOARD_HANDOFF.md`
**Supersedes:** Phase 2B sequencing as previously specified

---

## 1. Executive Summary

PulseWise Phase 1 is deployed. The next strategic question is not "what can we build" — both Phase 2A (customer-facing analytics) and Phase 2B (ERD Engine) have full handoff documents ready. The question is "what should we build, and in what order, to maximize value to the Wise World ecosystem."

The recommendation: **commit fully to Phase 2A and the natural extensions that flow from it (anomaly detection, cross-product correlation), and demote the ERD Engine to a future-work track**. The reason is not that the ERD Engine is wrong — it's that it solves a problem PulseWise does not yet have, while Phase 2A solves a problem VoiceWise's paying customers feel today.

The moat PulseWise is building is not "automated entity discovery." It is the AI-context schema and the feedback loop it enables — every event carries model, confidence, latency, and cost as first-class fields, which no general-purpose analytics platform does. Phase 2A is what makes that moat visible to customers. Phase 2B is what makes it scale to verticals you don't have yet. Sequence accordingly.

---

## 2. Strategic Assumptions

These are the bets the rest of the document rests on. If any of them turn out to be wrong, the plan needs revision.

**Assumption 1 — VoiceWise revenue is the near-term pressure point.** VoiceWise has live customers on $49/$99/$199 plans. PulseWise's primary job in the next 6 months is to make VoiceWise more sellable and stickier. Hopwise, HelmerWise, and ScriptWise are downstream beneficiaries.

**Assumption 2 — Build velocity is constrained by single-developer bandwidth.** The Voicewise tracker flags "single contributor" as a medium risk. This roadmap assumes one person doing focused work, not a team. Phases are sized accordingly.

**Assumption 3 — No external funding clock is ticking.** The roadmap optimizes for product-market fit and ecosystem coherence, not burn-rate milestones. If funding is raised and a hiring plan kicks in, this changes — flag it and revisit.

**Assumption 4 — PulseWise stays internal in the near term.** Externalization (selling PulseWise as a product) is on the long-horizon roadmap but not in the next 6 months. The architecture stays multi-tenant-ready, but no productization work happens yet.

**Assumption 5 — Document-first process holds.** Every phase produces a self-contained handoff document before any implementation. This roadmap assumes that constraint and sequences phases to fit it.

**Assumption 6 — The Wise World product slate is roughly stable.** VoiceWise and Hopwise are real. HelmerWise, ScriptWise, AgentWise are planned but not actively in build. If a new product enters active development sooner than expected, the cross-product capabilities (Phase 2A.6, MDM) become more urgent.

If any assumption above is wrong, it is the user's call to flag it before this roadmap is locked.

---

## 3. The Horizons

Strategic planning needs three time horizons, each with a clear definition of "what does success look like." This is what they are for PulseWise.

### Horizon 1 — Six Months (May 2026 → October 2026)

**What success looks like:** Every Wise World product in active development emits PulseWise events with tenant scoping, and every product that has paying customers exposes a customer-facing analytics dashboard powered by PulseWise. VoiceWise restaurants see their ROI numbers. Hopwise (when it ships to customers) inherits the same capability for free. PulseWise stops being internal telemetry and becomes the analytics layer of the ecosystem.

**Concretely measurable:** At least two products consume PulseWise's customer-facing analytics API in production. Dashboard load times stay under 500ms. At least one anomaly per week is surfaced to a Wise World operator before the customer notices.

### Horizon 2 — One Year (November 2026 → April 2027)

**What success looks like:** PulseWise is no longer just reporting what happened — it is actively feeding signal back into the products that emit events. VoiceWise's routing decisions improve because PulseWise tells it which provider performs best for which caller segment. Hopwise's recommendation ranking improves because PulseWise knows which destinations convert for which traveler segments. Cross-product insights exist (e.g., "users who bounce from Hopwise call VoiceWise more often"). The ERD Engine, if built, is justified by genuine new-vertical onboarding.

**Concretely measurable:** At least one production product uses PulseWise data as a real-time input to a model decision (not just a dashboard read). At least one cross-product insight is documented and acted on.

### Horizon 3 — Three Years (April 2027 → April 2029)

**What success looks like:** PulseWise is a productizable asset — either externalized as a paid product to other AI-native companies, or formally positioned as a defensible moat in fundraising or acquisition conversations. The AI-context schema is mature enough that other companies want to adopt it. The ERD Engine, if built and proven internally, becomes a genuine differentiator at this stage.

**Concretely measurable:** Either external customers exist, or PulseWise is documented as a strategic asset in the WorldWise LLC capitalization story.

---

## 4. Phased Roadmap (Now / Next / Later)

This is the operational plan. Each phase has explicit exit criteria — Phase N+1 does not begin until Phase N is shipped. The handoff-document constraint applies to every phase.

### NOW — May 2026 (4–6 weeks)

#### Phase 2A — Customer-Facing Analytics Dashboard
**Status:** Handoff document exists (`PULSEWISE_ANALYTICS_DASHBOARD_HANDOFF.md`). Architect review needed before implementation.

**Deliverables:**
- `tenant_id` added to PulseEvent schema and SDK (backward compatible)
- Three rollup tables (hourly, daily, monthly) with vertical-flexible JSONB breakdowns
- Tenant-scoped analytics API (`/analytics/{tenant_id}/*`)
- Cost savings + ROI computation grounded in vertical baselines
- VoiceWise integration — restaurant dashboard renders from PulseWise data

**Exit criteria:**
- Two test restaurants on VoiceWise see distinct, correctly-scoped dashboards
- Phase 1 backward compatibility holds (events without `tenant_id` still ingest)
- Dashboard API responds in <500ms for tenants with 1,000 daily events
- All open questions in the handoff document have architect-approved answers

**Why this is NOW:** It is the highest-leverage work that exists. It directly impacts VoiceWise's sellability. It unlocks Hopwise's analytics for free. It establishes the multi-tenant foundation every future phase depends on.

#### Phase 2B.1 — Data Standards Module (salvage)
**Status:** Handoff document exists (`PULSEWISE_ERD_PHASE_2B1_HANDOFF.md`). Implementable today.

**Deliverables:**
- `config/data_standards.py` — `LogicalType` enum, type mappings, naming conventions, PII detection
- `core/erd_models.py` — Pydantic models (`FieldProfile`, `DiscoveredEntity`, `EntityRelationship`, etc.)
- `migrations/003_erd_engine_tables.sql` — three new tables
- 32+ tests passing

**Exit criteria:** As specified in the existing 2B.1 handoff.

**Why this is NOW (despite demoting Phase 2B overall):** The standards module is genuinely foundational infrastructure — it formalizes the type system that Phase 2A's rollup engine *should also use*. The work is small (~1 week), the tests are already specified, and the output is reusable regardless of whether the rest of Phase 2B ever gets built. **Salvaging this is cheap; rebuilding it later is expensive.** The Pydantic ERD models are dead weight if Phase 2B never ships, but their cost (a few hundred lines of validated dataclasses) is trivial.

**Critical sequencing note:** Phase 2A's rollup engine should adopt `LogicalType` from Phase 2B.1. This means 2B.1 ships *before or alongside* 2A, not after. The Technical Architect should confirm this before 2A implementation begins.

---

### NEXT — June 2026 → August 2026 (6–8 weeks)

#### Phase 2A.5 — Anomaly Detection Layer
**Status:** Not yet specified. Handoff document needed before implementation.

**Deliverables:**
- Rolling baseline computation per tenant per metric (success rate, latency, cost, volume)
- Deterministic anomaly flagging — z-score and percent-deviation thresholds
- Correlation analysis — when an anomaly fires, automatically surface what else changed
- Anomaly storage and API (`/analytics/{tenant_id}/anomalies`)
- Optional Claude call only at the *end* — generate a one-line explanation grounded in the anomaly + correlation data

**Exit criteria:**
- At least one anomaly type (success rate drop) is detected end-to-end
- Anomalies appear in the VoiceWise dashboard with actionable context
- Cold-start handling — works correctly for tenants with <7 days of data
- False positive rate <20% on retrospective data

**Why this is NEXT:** Phase 2A delivers dashboards. Dashboards are useful but passive — a restaurant owner has to look at them. Anomalies are active — they push something to the operator's attention. This is what makes PulseWise feel intelligent rather than just informative. It also separates LLM use into the right layer: detection and correlation are deterministic (cheap, reliable), narrative is LLM (expensive, optional).

#### Phase 2A.6 — Cross-Product Correlation
**Status:** Not yet specified. Depends on 2A and on having two products emitting tenant-scoped events.

**Deliverables:**
- A `user_cohort` or `entity_link` mechanism for joining users/sessions across products
- Cross-product analytics queries (e.g., "Hopwise users who churned: do they call VoiceWise more?")
- An API surface that lets a Wise World operator pull cross-product insights
- A first concrete example of acted-on cross-product signal documented in the project tracker

**Exit criteria:**
- Two products' events can be joined on a common entity (user or session) without breaking tenant isolation
- At least one cross-product insight is surfaced and demonstrably actionable
- The architecture supports adding a third product (HelmerWise, ScriptWise) without re-design

**Why this is NEXT:** This is the first capability that is genuinely impossible on Mixpanel, Amplitude, or any other analytics platform — because no other platform owns events from all your products with consistent schema. It is the first concrete proof of the moat. It is also the foundation for the eventual MDM functionality that Phase 2B's ERD Engine would automate; doing it manually first informs whether automation is needed.

---

### LATER — September 2026 onward

The "Later" bucket is intentionally less precise. It contains options, not commitments. The choice between them happens at the decision point in Section 8.

#### Option L1 — Active Feedback Loop
PulseWise data becomes a real-time input to product decisions, not just a dashboard read. VoiceWise's routing engine queries PulseWise for "which provider performs best for this caller profile right now." Hopwise's ranker queries PulseWise for "which destinations convert for travelers like this one." This is Horizon 2's defining capability.

#### Option L2 — ERD Engine (the demoted Phase 2B)
Build the Schema Sampler, Entity Inference, Relationship Mapper, and ERD Renderer as previously specified. Justified only when (a) a third or fourth Wise World vertical enters active development and the manual data-modeling overhead per vertical becomes a real bottleneck, OR (b) external customers are imminent and auto-configuration becomes a sales differentiator.

#### Option L3 — External productization
Package PulseWise as a sellable product to other AI-native companies. Requires API key auth, customer onboarding flows, billing, multi-tenant security hardening, public docs, and sales positioning. Roughly 3 months of dedicated work. Justified only when internal use proves the moat and a clear external buyer profile exists.

#### Option L4 — Real-time tier
Some products may eventually need sub-minute analytics (live call dashboards, live recommendation A/B tests). This requires either streaming infrastructure (Kafka/Kinesis) or a synchronous write path to rollups. Significant architectural work. Justified only when an internal product genuinely cannot live with 15-minute rollup latency.

The "Later" track stays open. The sequencing decision happens after Phase 2A.6 ships, with real data to inform it.

---

## 5. What Changes vs. the Prior Implicit Plan

The prior plan, as implied by existing handoff documents, was: Phase 2A and Phase 2B in parallel, with Phase 2B carrying significant weight. This roadmap rebalances.

| Item | Prior Status | New Status | Rationale |
|---|---|---|---|
| Phase 2A — Analytics Dashboard | Parallel with 2B | **NOW, primary focus** | Direct revenue impact via VoiceWise; foundation for everything downstream |
| Phase 2B.1 — Data Standards | First sub-phase of 2B | **NOW, salvaged as foundation** | Genuinely useful regardless of ERD Engine; cheap to ship; should be adopted by 2A's rollup engine |
| Phase 2B.2 — Schema Sampler | Next after 2B.1 | **LATER** | Solves a problem we don't have (only 2 verticals exist) |
| Phase 2B.3 — Entity Inference | Pending | **LATER** | Needs more event data and more verticals to be valuable |
| Phase 2B.4–2B.6 — Mapper/Renderer/Orchestrator | Pending | **LATER** | All depend on 2B.2 and 2B.3 |
| Phase 2A.5 — Anomaly Detection | Not previously planned | **NEXT** | Turns dashboards into decision tools; separates LLM cost from analytics logic |
| Phase 2A.6 — Cross-Product Correlation | Not previously planned | **NEXT** | First capability impossible on competing platforms; concrete moat proof |

The total scope change: roughly 4–6 weeks of work that was previously scoped for Phase 2B.2-2B.6 is deferred indefinitely; roughly 6–8 weeks of new work (2A.5 and 2A.6) takes its place in the "Next" slot. Net velocity is similar. Strategic value of work-in-flight is meaningfully higher.

---

## 6. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **VoiceWise customers churn before Phase 2A ships** because they can't see analytics | Medium | High | Ship Phase 2A on a 4–6 week timeline; if it slips past 8 weeks, build a minimal "dashboard v0" with raw queries against `pulse_events` as a stopgap |
| **Solo developer bandwidth becomes a hard bottleneck** — phases stack up | High | Medium | Keep handoff docs detailed enough that contractors or future hires can pick up phases independently; do not let Claude Code build without a handoff |
| **Phase 2A's rollup engine ships without adopting 2B.1's `LogicalType`** — type drift between modules | Medium | Medium | Architect review at Phase 2A kickoff explicitly verifies 2B.1 standards adoption |
| **A new Wise World product enters active build before Phase 2A.6 ships** — cross-product foundation is missing when needed | Low | High | If HelmerWise or ScriptWise enters active build, prioritize 2A.6 over 2A.5 |
| **VoiceWise's TASK-011 (auth) and TASK-013 (PII redaction) ship late** — PulseWise's tenant-scoped API has no upstream auth boundary | Medium | High | Phase 2A explicitly does NOT add auth to PulseWise; document this dependency clearly. If VoiceWise auth slips, do not expose PulseWise's analytics API to public internet under any circumstance |
| **Anomaly detection produces too many false positives** — operators ignore alerts | Medium | Medium | Phase 2A.5 ships with conservative thresholds and a "tune before broadening" plan; track false positive rate explicitly |
| **The "moat" framing is wrong** — competitors (Helicone, Langfuse, LangSmith) catch up faster than expected | Low | Medium | At Phase 2A.6 completion, do focused market research (Section 7 of prior strategic note) to confirm positioning still holds |
| **PulseWise's standalone Railway service goes down** — VoiceWise/Hopwise can't see their dashboards even though circuit breaker keeps them running | Medium | Medium | Add basic uptime monitoring; degraded-state UX in consumer dashboards ("data temporarily unavailable") so customers see something rather than blank screens |
| **Cross-product correlation surfaces a privacy issue** — joining users across products reveals something a tenant didn't consent to | Low | High | Phase 2A.6 design must include a privacy review before implementation; tenant isolation rules from 2A apply transitively |

---

## 7. Alternative Path

The primary recommendation is "internal first, externalize later." The most plausible alternative is "externalize sooner."

**The alternative path:** After Phase 2A ships, instead of building 2A.5 and 2A.6, pivot to productizing PulseWise — add API key auth, customer onboarding, public docs, billing integration, and sales positioning. Treat the AI-context schema as the product and sell it to other AI-native companies.

**What would make this the right choice:**
- An external customer or design-partner candidate emerges in the next 1–2 months who is willing to pay for PulseWise *as it exists post-2A*
- Wise World's funding or strategic situation makes "external revenue from PulseWise" a higher priority than "improving VoiceWise's product"
- Competitive pressure from Helicone / Langfuse / LangSmith accelerates and PulseWise needs to plant a flag externally before they close the gap

**What argues against it today:**
- No external customer is in hand, and finding one is a separate, time-consuming workstream
- Phase 2A is what makes PulseWise's value *legible* to external customers anyway — selling a product without a polished dashboard is harder
- Internal use across two products is what produces the testimonials, case studies, and reference data that external sales need
- Anomaly detection and cross-product correlation are genuinely differentiating capabilities that are easier to build first internally than to design from scratch for external customers

The recommendation is to keep this alternative on the shelf and revisit at the decision point after Phase 2A.6. Don't pre-commit either way.

---

## 8. Decision Points

Strategic plans need explicit moments where the team pauses and re-evaluates. Three for this roadmap.

### Decision Point 1 — Post Phase 2A (≈ June 2026)

**The question:** Did Phase 2A actually move the needle on VoiceWise's sales/retention?

**Information needed:**
- VoiceWise customer feedback on the dashboard — qualitative
- Any retention or upgrade signal that correlates with dashboard launch
- Internal time spent answering "how is my restaurant doing" questions, before vs. after

**The branches:**
- **If yes:** Proceed confidently into Phase 2A.5 (anomaly detection)
- **If unclear:** Spend a week on focused customer interviews before deciding what to build next
- **If no:** Stop and reconsider — maybe the dashboard isn't where the value is, and the roadmap needs a deeper rewrite

### Decision Point 2 — Post Phase 2A.6 (≈ August/September 2026)

**The question:** What's the highest-leverage next phase — active feedback loop, ERD Engine, externalization, or real-time tier?

**Information needed:**
- How many Wise World products are now in active development with PulseWise integration
- Whether any external customer has surfaced as a serious prospect
- Whether VoiceWise's routing or Hopwise's ranking has reached a complexity ceiling that PulseWise data could break through
- Competitive positioning research (this is when to do the focused market research from Section 7 of the prior strategic note)

**The branches:**
- **2+ new products in active build:** ERD Engine becomes more justified
- **External customer in hand:** Pivot to externalization (Option L3)
- **Routing/ranking complexity ceiling hit:** Active feedback loop (Option L1)
- **None of the above:** Default to active feedback loop as the highest internal-value option

### Decision Point 3 — Post Horizon 1 (≈ October/November 2026)

**The question:** Is PulseWise on track to be a strategic asset by the 3-year horizon, or is it just internal infrastructure?

**Information needed:**
- Whether PulseWise has produced insights or capabilities that competitors cannot easily replicate
- Whether the AI-context schema has been formalized to a point where it could be published or standardized
- Whether external interest has materialized organically (inbound inquiries, conference talks, GitHub stars on any open-sourced piece)

This is the moment to either commit to the long-horizon productization path or formally classify PulseWise as "internal-only forever." Either is fine — but the decision should be conscious, not drift.

---

## 9. The Moat (Restated)

A strategic plan needs a clear answer to "why does this matter." For PulseWise, the answer is not "automated entity discovery" — that is a feature, possibly a powerful one, but not the core moat.

The moat has three layers, ordered by how visible and how durable they are.

**Layer 1 — The AI-context schema.** Every event has model, confidence, latency, and cost as first-class fields. No general-purpose analytics platform does this. Every AI-native product has had to bolt this onto Mixpanel via custom properties, which is fragile and doesn't aggregate well. PulseWise gets it right by default. This is the most easily articulable advantage and the one that should anchor positioning.

**Layer 2 — The cross-product event substrate.** Wise World products share a single event store with consistent schema. This is what makes Phase 2A.6 (cross-product correlation) possible at all, and it cannot be replicated by a third-party analytics tool that sees only one product's events. Every additional product that integrates compounds this advantage.

**Layer 3 — The intelligence loop.** When PulseWise data flows back into product decisions (Horizon 2), every product gets smarter from every other product's data. This is the long-horizon moat — by the time a competitor catches up to Layer 1 and Layer 2, PulseWise has years of operational learning baked into its rollups, anomaly thresholds, and (eventually) entity model.

The roadmap is sequenced to make these layers visible in order: Phase 2A makes Layer 1 visible to customers, 2A.6 makes Layer 2 visible to operators, and Horizon 2 makes Layer 3 visible everywhere. The ERD Engine, when built, is a tool for scaling Layer 2 to verticals you don't have yet — useful, but downstream of the layers that matter most.

---

## 10. What Happens Next

This roadmap is a strategic document, not an implementation plan. To translate it into action:

1. **Architect review of Phase 2A** — confirm `LogicalType` adoption from Phase 2B.1, resolve the open questions in `PULSEWISE_ANALYTICS_DASHBOARD_HANDOFF.md`, and produce the architect-reviewed Phase 2A handoff.
2. **Implement Phase 2B.1 in parallel or first** — it's small enough to ship in a week and unblocks 2A's adoption of standardized types.
3. **Implement Phase 2A** — Claude Code consumes the architect-reviewed handoff.
4. **Write the Phase 2A.5 handoff** — anomaly detection is currently unspecified. The Technical Architect should design it once 2A is shipping, not before.
5. **Run Decision Point 1** when 2A is live and producing real dashboards.

The Supervisor role should track each of these as discrete milestones. The Strategist (this role) does not produce more output until Decision Point 1 surfaces new information that warrants re-planning.

---

*End of roadmap.*
