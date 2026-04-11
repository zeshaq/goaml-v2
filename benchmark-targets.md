# goAML-v2 Benchmark Targets

> Commercial-product benchmark guide for goAML-v2. This document identifies mature platforms to compare against, explains why each one matters, and maps each benchmark target to the relevant goAML-v2 capabilities.

## 1. Purpose

`goAML-v2` is now far enough along that the right question is no longer "what features should we build in theory?" but "which mature products should we compare ourselves to, and for which workflows?"

This document is meant to help with:

- product strategy
- UX benchmarking
- feature-gap analysis
- prioritization
- demo positioning

The goal is not to copy one product blindly. The goal is to benchmark different parts of `goAML-v2` against the vendors that are strongest in those areas.

## 2. Benchmarking Principle

No single commercial AML suite is the perfect benchmark for every area.

For `goAML-v2`, the most useful approach is:

- benchmark `workflow depth` against large enterprise AML suites
- benchmark `graph/contextual investigation` against decision-intelligence products
- benchmark `screening/data workflows` against API-first compliance vendors
- benchmark `analyst UX and speed` against modern operations-first products

That gives a more realistic target than trying to mirror one vendor end to end.

## 3. Recommended Benchmark Set

### 3.1 NICE Actimize

Best benchmark for:

- transaction monitoring
- enterprise case management
- sanctions screening
- alert triage workflow depth
- large-bank AML operating model

Why it matters:

- one of the most established enterprise AML benchmarks
- strong end-to-end AML operating model
- useful reference for how deep queue, case, and review workflows should feel

What to compare in `goAML-v2`:

- `Alert Desk`
- `Case Command Center`
- reviewer / approver queues
- playbook-driven investigation workflow
- filing readiness and SAR lifecycle

Reference:

- [NICE Actimize AML Essentials](https://www.niceactimize.com/aml-essentials)

### 3.2 Nasdaq Verafin

Best benchmark for:

- integrated case management
- sanctions and watchlist workflow
- analyst investigation experience
- mid-market and bank operations ergonomics

Why it matters:

- strong reputation for investigation workflow and operational usability
- useful comparison point for how the analyst product should feel day to day

What to compare in `goAML-v2`:

- `Control Tower`
- `Alert Desk`
- `Analyst Inbox`
- watchlist dashboard
- manager console

Reference:

- [Verafin Sanctions Screening Management](https://verafin.com/solution/sanctions-screening-management/)

### 3.3 Quantexa

Best benchmark for:

- graph-first investigation
- entity resolution
- network/contextual intelligence
- decision-intelligence workflows

Why it matters:

- probably the closest benchmark to the graph-heavy parts of `goAML-v2`
- especially relevant for entity resolution, network analysis, and contextual investigation

What to compare in `goAML-v2`:

- persisted Neo4j graph workflow
- graph drilldown and pathfinding
- entity profile and merge workflow
- watchlist network context
- investigation context assembly

Reference:

- [Quantexa](https://www.quantexa.com/)

### 3.4 Oracle Financial Crime and Compliance Management

Best benchmark for:

- large-enterprise AML controls
- rules and workflow depth
- traditional financial-crime operating model
- enterprise governance patterns

Why it matters:

- useful benchmark for completeness and control depth
- especially helpful when evaluating what still separates `goAML-v2` from a large-bank-grade suite

What to compare in `goAML-v2`:

- manager console
- workflow ops
- approval and control flow
- long-form operational reporting expectations

Reference:

- [PwC / Chartis AML monitoring market mention](https://www.pwc.com/gx/en/news-room/assets/analyst-citations/chartis_aml_transaction_monitoring-solutions.pdf)

### 3.5 SymphonyAI Sensa / NetReveal

Best benchmark for:

- financial crime analytics
- screening and monitoring depth
- enterprise investigation tooling

Why it matters:

- strong comparison point for high-volume monitoring and enterprise operational analytics
- useful when evaluating where `goAML-v2` still needs more reporting maturity

What to compare in `goAML-v2`:

- `Workflow Ops`
- `Reporting Studio`
- SLA analytics
- queue analytics
- screening and monitoring posture

References:

- [NetReveal / Chartis watchlist monitoring mention](https://www.netreveal.ai/wp-content/uploads/2023/03/Financial-Crime-Risk-Management-Systems-Watchlist-Screening-and-Monitoring-Solutions-2022-Part-2-FINAL-NO-WATERMARK.pdf)

### 3.6 ComplyAdvantage

Best benchmark for:

- API-first compliance workflows
- sanctions/PEP screening
- adverse media and modern screening UX
- modular deployment style

Why it matters:

- relevant to `goAML-v2` because the platform already has an API-driven, modular architecture
- good benchmark for how modern screening workflows should feel and scale

What to compare in `goAML-v2`:

- entity screening
- watchlist re-screen automation
- ongoing monitoring workflow
- screening result quality and UX

Reference:

- [ComplyAdvantage market comparison mention](https://www.fraud.net/resources/top-aml-software)

### 3.7 Unit21

Best benchmark for:

- analyst operations UX
- case management ergonomics
- saved views and queue handling
- compliance-ops productivity

Why it matters:

- one of the better references for a modern, configurable compliance operations product
- highly relevant for UX benchmarking rather than only AML feature benchmarking

What to compare in `goAML-v2`:

- saved views
- bulk triage
- `Analyst Inbox`
- launchpad / role-based desks
- manager console usability

Reference:

- [Unit21 custom report / AML market comparison mention](https://go.unit21.ai/hubfs/AML_LINK_INDEX_FINAL_CUSTOM%20REPORT_Unit21.pdf)

### 3.8 LexisNexis Risk Solutions / Moody's

Best benchmark for:

- screening-data depth
- due diligence context
- connected compliance intelligence
- external data enrichment

Why it matters:

- these are useful benchmarks not because `goAML-v2` should mimic their entire UI, but because they represent the depth of external compliance data and screening support mature products often rely on

What to compare in `goAML-v2`:

- screening quality
- entity enrichment expectations
- external intelligence depth
- investigation evidence support

References:

- [LexisNexis AML systems leaderboard mention](https://risk.lexisnexis.co.uk/-/media/files/financial%20services/lnrs%20-%20aml%20systems%20leaderboard%20reprint%201%20pdf.pdf)
- [Moody’s Compliance Catalyst description](https://aml-fraud.pl/en/moodys-compliance-catalyst)

## 4. Recommended Shortlist

If we want a smaller working shortlist instead of the full set above, these are the `5` strongest benchmark targets for `goAML-v2` right now:

- `NICE Actimize`
- `Nasdaq Verafin`
- `Quantexa`
- `Unit21`
- `ComplyAdvantage`

Why this shortlist:

- `NICE Actimize` gives the enterprise AML workflow benchmark
- `Verafin` gives the operations-and-investigation benchmark
- `Quantexa` gives the graph/context benchmark
- `Unit21` gives the modern analyst UX benchmark
- `ComplyAdvantage` gives the API-first screening benchmark

## 5. Benchmark Mapping to goAML-v2

| goAML-v2 Area | Best Benchmark Target | Why |
|---|---|---|
| Alert triage and case workflow | `NICE Actimize`, `Verafin` | Best reference for mature AML case-management flow and alert operations |
| Case Command Center | `Verafin`, `Unit21` | Good benchmark for day-to-day analyst ergonomics |
| Reviewer / approver queues | `NICE Actimize`, `Oracle` | Strong comparison for enterprise review controls and separation of duties |
| Manager Console | `Verafin`, `Oracle`, `SymphonyAI` | Strong benchmark for queue control, workload views, and operational oversight |
| Graph investigation | `Quantexa` | Closest benchmark for graph-driven contextual investigation |
| Entity resolution and watchlists | `Quantexa`, `Verafin` | Good benchmark for relationship-driven watchlist workflows |
| Screening workflow | `ComplyAdvantage`, `LexisNexis`, `Moody’s` | Best benchmark for screening quality, enrichment, and monitoring |
| Saved views / bulk triage / inbox | `Unit21` | Strong benchmark for productivity and modern compliance UX |
| Model Ops and scorer lifecycle | no single perfect AML benchmark | More comparable to internal MLOps + governance patterns than classic AML vendors |
| Reporting Studio / SLA analytics | `SymphonyAI`, `Oracle`, `NICE Actimize` | Good benchmark for ops reporting depth and managerial control |

## 6. How to Use These Benchmarks

Use the benchmark set in three layers:

### 6.1 Workflow Benchmarking

Questions to ask:

- how many clicks does it take to move from alert to case to SAR?
- how visible are blockers, SLA risk, and pending actions?
- how much analyst context is available without changing pages?

Most relevant targets:

- `NICE Actimize`
- `Verafin`
- `Unit21`

### 6.2 Investigation Intelligence Benchmarking

Questions to ask:

- how well does the product connect graph, documents, screening, and case evidence?
- how well does it explain risk and relationships?
- how strong is entity resolution and contextual drilldown?

Most relevant targets:

- `Quantexa`
- `LexisNexis`
- `Moody’s`

### 6.3 Ops and Governance Benchmarking

Questions to ask:

- how strong are queue controls, breach reporting, and manager tooling?
- how mature are review/approval controls?
- how much audit and governance depth is visible in the product itself?

Most relevant targets:

- `NICE Actimize`
- `Oracle`
- `SymphonyAI`

## 7. Current goAML-v2 Position Against These Targets

High-level read:

- strongest relative comparison:
  - graph/contextual investigation
  - integrated intelligence workflows
  - ML/model-governance foundation
- middle tier:
  - analyst workflow breadth
  - SAR review/approval flow
  - manager and queue operations
- largest remaining gaps:
  - workflow polish under heavy analyst volume
  - reporting/operations depth
  - row-level work partitioning
  - enterprise integration/hardening

Practical takeaway:

`goAML-v2` is no longer benchmarked best against prototypes or internal demos. It is ready to be benchmarked against serious commercial products by workflow category.`

## 8. Suggested Next Benchmark Exercises

1. Benchmark `Alert Desk`, `Case Command Center`, and `Manager Console` against `Verafin` and `Unit21`.
2. Benchmark graph, entity resolution, and watchlist workflows against `Quantexa`.
3. Benchmark screening and ongoing monitoring UX against `ComplyAdvantage` and `LexisNexis`.
4. Benchmark review/approval governance and manager reporting against `NICE Actimize` and `Oracle`.

## 9. Related Documents

- [goaml-v2-project-overview-v3.md](/Users/ze/Documents/goaml-v2/goaml-v2-project-overview-v3.md)
- [implementation-plan-v3.md](/Users/ze/Documents/goaml-v2/implementation-plan-v3.md)
