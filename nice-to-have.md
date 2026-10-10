# KPI Dashboard: Nice-to-Have Metrics

These metrics add to the **Startup KPI Dashboard Requirements Spec**. The core spec covers the primary metric, growth rate, revenue/MRR, burn, runway, cohort retention, and the module metrics (net dollar retention, gross margin, CAC, organic share, NPS, unit economics).

The metrics below are **diagnostic**. They go on a separate "Diagnostics" page, not the weekly home page. Look at them when a headline number moves and you need to know why.

They are ranked by value to an early-stage startup. Rank 1 is the most useful.

> **Benchmarks:** figures marked *(YC)* come from Y Combinator Startup School talks. Figures marked *(industry)* are common investor rules of thumb, not YC guidance. Treat both as starting points, not targets.

---

## Summary ranking

| Rank | KPI | Measures | Applies to | Frequency |
|---|---|---|---|---|
| 1 | Conversion funnel | Where people drop off between first visit and paying | All | Weekly |
| 2 | Free-to-paid conversion | Whether users value the product enough to pay | Freemium / trial | Weekly, by cohort |
| 3 | CAC payback period | How fast acquisition spend is earned back | Anyone spending on acquisition | Monthly |
| 4 | Burn multiple | Cash spent per $1 of new recurring revenue | Recurring revenue, fundraising | Monthly |
| 5 | Customer concentration | Dependence on a few large customers | B2B | Monthly |
| 6 | DSO / accounts receivable | Revenue invoiced but not yet collected as cash | B2B, invoice-based | Monthly |
| 7 | Time to value | How quickly a new user gets their first real result | All | Weekly |
| 8 | Sales pipeline | Future revenue in progress and its health | B2B with a sales process | Weekly |
| 9 | Win rate | Share of qualified deals that close | B2B with a sales process | Monthly |
| 10 | Sales cycle length | Days from first contact to signed deal | B2B with a sales process | Monthly |
| 11 | Pilot-to-paid conversion | Whether pilots turn into paying contracts | B2B running pilots | Monthly |
| 12 | Stickiness (DAU/WAU, WAU/MAU) | How habitual usage is | Consumer, daily-use products | Weekly |
| 13 | Quick ratio | Quality of growth: revenue gained vs revenue lost | Recurring revenue | Monthly |
| 14 | Support tickets per active customer | Product friction and onboarding problems | All | Weekly |
| 15 | Revenue per employee | Team efficiency | All, once past ~5 people | Monthly |
| 16 | Hiring plan vs actual | Whether payroll (the biggest cost) is on plan | All | Monthly |
| 17 | Uptime and error rate | Reliability | Infrastructure, APIs, mission-critical products | Daily |

---

## 1. Conversion funnel

**What it measures:** the percentage of people who move from each stage to the next. The stages are: visitor → sign-up → activated (performed the key action) → paying.

**Formula:**

```
stage_conversion(n) = people reaching stage n+1 in period ÷ people reaching stage n in period
overall_conversion  = paying customers ÷ visitors (same cohort)
```

Measure each stage by **cohort**: people who entered the funnel in week W. Don't divide this week's payers by this week's visitors, because many of this week's payers arrived in earlier weeks.

**How to track:**
- Visitors: web analytics (unique visitors, with UTM source)
- Sign-up: `customers.created_at`
- Activated: `customers.first_key_action_at`
- Paying: `customers.first_paid_at`
- New table or view: `funnel_weekly` (cohort_week, stage, count, conversion_pct), sliced by channel and segment

**Why it's useful:** retention tells you *whether* the product works. The funnel tells you *where* you're losing people. A bad visitor-to-sign-up rate points to positioning or the landing page. Bad sign-up-to-activation points to onboarding. Bad activation-to-paid points to pricing or value.

**Watch out for:** conversion rate on its own is a poor test of product-market fit *(YC, Gustaf Alströmer)*. It tells you nothing about who converted or whether they stayed. Always read it alongside retention.

---

## 2. Free-to-paid conversion

**What it measures:** the share of free or trial users who become paying customers.

**Formula:**

```
free_to_paid(cohort) = customers in cohort with first_paid_at within N days ÷ cohort size
```

N = trial length, or 30/60/90 days for freemium.

**How to track:** `customers.created_at` and `customers.first_paid_at`. Add `customers.plan_at_signup` (free / trial / paid) if it isn't there.

**Why it's useful:** free users give weaker feedback and are weak evidence of demand. YC's advice is to "just get paid" *(YC, Adora Cheung)*. This number shows whether free usage turns into revenue.

**Benchmark:** varies widely by model. Track the trend by cohort rather than chasing an absolute number.

---

## 3. CAC payback period

**What it measures:** how many months of gross profit from a customer it takes to earn back the cost of acquiring them.

**Formula:**

```
CAC            = marketing_spend (channel, period) ÷ new retained customers from that channel
monthly_GP     = (revenue − variable costs) per customer per month
CAC_payback    = CAC ÷ monthly_GP
```

"Retained" means the customer is still active after an agreed point, such as week 4. Counting raw sign-ups makes CAC look cheaper than it is *(YC, Tom Blomfield)*.

**How to track:** `marketing_spend`, `customers.acquisition_channel`, `transactions`, `variable_costs`. Report per channel, never only as a blended figure.

**Why it's useful:** it's easier to act on than LTV, because LTV relies on guessing how long customers will stay, which young companies can't know yet. A long payback period means your growth uses up cash.

**Benchmark:** early-stage startups should aim to recover CAC within 1–3 months, or by the first transaction *(YC, Gustaf Alströmer)*. Don't fund paid acquisition before you have revenue *(YC)*.

---

## 4. Burn multiple

**What it measures:** how much cash you burn for each $1 of new annual recurring revenue (ARR) you add.

**Formula:**

```
burn_multiple = net burn (period) ÷ net new ARR (same period)
net new ARR   = (MRR end − MRR start) × 12
```

**How to track:** net burn from `cash_ledger` (excluding financing). MRR from `subscriptions`. Use quarterly figures to smooth out noise.

**Why it's useful:** it combines growth and cost efficiency in one number. Investors increasingly ask for it, especially when capital is expensive.

**Benchmark *(industry)*:** under 1 is excellent, 1–1.5 good, 1.5–2 acceptable, over 3 a concern. It isn't meaningful when net new ARR is zero or negative; show "n/a" with the reason.

---

## 5. Customer concentration

**What it measures:** how dependent revenue is on your largest customers.

**Formula:**

```
top1_share = revenue from largest customer ÷ total revenue
top5_share = revenue from 5 largest customers ÷ total revenue
```

Use trailing-3-month revenue to avoid one-off spikes.

**How to track:** `transactions` grouped by `customer_id`. Show it as a ranked bar of the top 10, with the top-1 and top-5 shares as cards.

**Why it's useful:** losing one large customer can cut revenue sharply, and investors and acquirers discount concentrated revenue. It also warns you when the product is turning into custom work for a single client.

**Benchmark *(industry)*:** a top-1 share above ~20–30% is a risk worth flagging. Concentration is normal very early on; the trend should fall as you add customers.

---

## 6. DSO / accounts receivable

**What it measures:** how long customers take to pay you, and how much invoiced revenue is still uncollected.

**Formula:**

```
DSO = accounts receivable at period end ÷ revenue in period × days in period
AR ageing buckets: current, 1–30, 31–60, 61–90, 90+ days overdue
```

**How to track:** add `invoices` (invoice_id, customer_id, amount, issued_at, due_at, paid_at) if billing is invoice-based. Pull it from the accounting system.

**Why it's useful:** burn and runway are measured in **cash**, not revenue *(YC, Tim Brady)*. Unpaid invoices don't extend runway. DSO explains why the revenue page and the cash page disagree.

**Benchmark *(industry)*:** close to your payment terms (e.g. 30–45 days on net-30). A rising 90+ day bucket needs action now.

---

## 7. Time to value

**What it measures:** how quickly a new user gets their first meaningful result.

**Formula:**

```
time_to_value = median(first_key_action_at − created_at), by cohort
```

Use the median, not the mean, because a few very slow users distort an average.

**How to track:** `customers.created_at` and `customers.first_key_action_at`. Slice by channel, platform and segment.

**Why it's useful:** users who reach value fast are more likely to stay. YC points to onboarding as often "the cheapest and easiest way" to improve retention *(YC, David Lieb)*, and recommends getting users to the "magic moment" as soon as possible *(YC, Tom Blomfield)*.

**Benchmark:** no universal number. It should fall over time as onboarding improves.

---

## 8. Sales pipeline

**What it measures:** the value and count of open deals at each sales stage.

**Formula:**

```
pipeline_value(stage)   = Σ deal amount for open deals in stage
weighted_pipeline       = Σ (deal amount × stage probability)
pipeline_coverage       = weighted_pipeline ÷ revenue target for the period
```

**How to track:** new table `deals` with fields deal_id, customer_id, stage, amount, currency, probability, source, owner, created_at, stage_changed_at, closed_at, outcome (won / lost / open), lost_reason. Usually synced from the CRM.

**Why it's useful:** in B2B, revenue lags sales activity by months. The pipeline shows next quarter's revenue before it arrives.

**Benchmark *(industry)*:** weighted coverage of 3× the target is a common rule. Keep stage definitions fixed, just like metric definitions.

---

## 9. Win rate

**What it measures:** the share of decided deals you win.

**Formula:**

```
win_rate = deals won ÷ (deals won + deals lost), by period closed
```

Exclude open deals. Slice by source, segment and deal size.

**How to track:** `deals.outcome`, `deals.closed_at`. Record `lost_reason` on every lost deal.

**Why it's useful:** it shows whether the problem is product or pitch (low win rate) or lead volume (good win rate, too few deals). Lost reasons tell you what to build or change.

---

## 10. Sales cycle length

**What it measures:** the time from first contact to a signed deal.

**Formula:**

```
sales_cycle = median(closed_at − created_at) for won deals
```

**How to track:** `deals.created_at`, `deals.closed_at`, `deals.outcome = won`.

**Why it's useful:** it drives realistic growth targets and cash planning. YC notes that enterprise sales start slow, and that time-to-sale should fall from months to days as the company matures *(YC, Adora Cheung)*.

---

## 11. Pilot-to-paid conversion

**What it measures:** the share of pilots that become paying contracts.

**Formula:**

```
pilot_to_paid = pilots converted to paid contracts ÷ pilots completed
```

**How to track:** add `deal_type` (pilot / contract) and `converted_from_deal_id` to `deals`.

**Why it's useful:** pilots that never convert are free work that looks like traction. YC's sales playbook advises structuring pilots to convert to paid contracts, such as paid pilots or opt-out contracts *(YC, Tom Blomfield)*.

---

## 12. Stickiness (DAU/WAU or WAU/MAU)

**What it measures:** how often active users come back within a longer period. In other words, how habitual the product is.

**Formula:**

```
DAU/WAU = average daily active users in week ÷ weekly active users in that week
WAU/MAU = average weekly active users in month ÷ monthly active users in that month
```

"Active" uses the same key action as the core spec.

**How to track:** `events` where `is_key_action = true`, with distinct `customer_id` counts per day, week and month.

**Why it's useful:** it separates products people use daily from ones they forget. Only use it where frequent use is the intended pattern; YC warns against forcing the wrong usage period *(YC, David Lieb)*.

**Benchmark *(industry)*:** DAU/WAU above ~0.4 is strong for daily-use consumer apps. It's irrelevant for products used occasionally, such as travel.

---

## 13. Quick ratio (recurring revenue)

**What it measures:** recurring revenue gained relative to recurring revenue lost.

**Formula:**

```
quick_ratio = (new MRR + expansion MRR + reactivation MRR) ÷ (churned MRR + contraction MRR)
```

**How to track:** the MRR movement bridge already in the spec (`subscriptions.change_type`).

**Why it's useful:** two companies can grow at the same rate with very different health. One adds a lot and loses little; the other has to keep refilling a leaky bucket. This puts the leaky-bucket idea *(YC, Tom Blomfield)* into one number.

**Benchmark *(industry)*:** above 4 is strong. Below 1 means recurring revenue is shrinking.

---

## 14. Support tickets per active customer

**What it measures:** how much help customers need.

**Formula:**

```
tickets_per_active = support tickets opened in week ÷ active customers in week
```

Also track median first-response time and the top 5 ticket categories.

**How to track:** export from the helpdesk tool into a new table `support_tickets` with fields ticket_id, customer_id, category, created_at, first_response_at, resolved_at. Store only the customer_id, not personal details.

**Why it's useful:** a rising rate usually points to onboarding gaps, bugs or confusing features. Support is also a variable cost that feeds unit economics *(YC, Tom Blomfield)*.

---

## 15. Revenue per employee

**What it measures:** revenue generated per full-time-equivalent employee.

**Formula:**

```
revenue_per_employee = annualised revenue ÷ FTE headcount at period end
```

**How to track:** new table `headcount` (month, fte_count, department). Pull it from HR or payroll as aggregate counts only; no salary or personal data.

**Why it's useful:** it's a simple efficiency check as the team grows, and it shows whether hiring is ahead of revenue.

---

## 16. Hiring plan vs actual

**What it measures:** actual headcount and payroll cost against plan.

**Formula:**

```
headcount_variance = actual FTE − planned FTE
payroll_variance   = actual payroll cash − planned payroll cash
```

**How to track:** add `planned_fte` and `planned_payroll` to the `headcount` table. Actual payroll comes from `cash_ledger.category = payroll`.

**Why it's useful:** payroll is usually the largest part of burn. Hiring ahead of plan is the most common way runway shrinks unexpectedly.

---

## 17. Uptime and error rate

**What it measures:** reliability of the product.

**Formula:**

```
uptime_pct  = (total minutes − downtime minutes) ÷ total minutes
error_rate  = failed requests ÷ total requests
```

**How to track:** from the monitoring tool (status page, APM). Load daily aggregates only.

**Why it's useful:** only where reliability *is* the product: APIs, infrastructure, payments, healthcare, or anything a customer's operations depend on. It's also needed if you offer an SLA (service-level agreement).

**Benchmark *(industry)*:** set by your SLA. 99.9% is about 43 minutes of downtime a month.

---

## New data the builder will need

| Table | Needed for | Key fields |
|---|---|---|
| `funnel_weekly` (view) | #1 | cohort_week, stage, count, conversion_pct, channel |
| `invoices` | #6 | invoice_id, customer_id, amount, currency, issued_at, due_at, paid_at |
| `deals` | #8–11 | deal_id, customer_id, deal_type, stage, amount, probability, source, created_at, closed_at, outcome, lost_reason, converted_from_deal_id |
| `support_tickets` | #14 | ticket_id, customer_id, category, created_at, first_response_at, resolved_at |
| `headcount` | #15–16 | month, department, fte_count, planned_fte, planned_payroll |
| `customers.plan_at_signup` (new column) | #2 | free / trial / paid |

Visitors for the funnel come from web analytics; uptime and error rate come from the monitoring tool. Both load as daily aggregates.

## Metrics to leave out

These numbers can rise while the business stagnates, so they shouldn't appear as headline KPIs: page views, total registered users, app downloads, social followers, email sign-ups, and GMV or gross transaction value shown as if it were revenue *(YC, Tom Blomfield; Gustaf Alströmer)*.
