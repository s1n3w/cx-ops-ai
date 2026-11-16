# Labeling guide

Written before any model run. Every gold label in `data/tickets/` and `data/surveys/` follows these rules.
All data is made up: "Tallyline" is a fictional B2B SaaS for small professional-services firms
(time tracking, invoicing, client portal, payments, integrations). No real customer data is used.

## Tickets

**category** (one per ticket: the customer's main ask)

| category | meaning |
|---|---|
| billing | Tallyline's own subscription: plans, charges, cards, receipts, seats, refunds |
| access | Can't log in, passwords, 2FA, SSO, user invites, ownership |
| bug | Something in the product is broken or behaving wrong |
| how_to | How do I use a feature (invoices, payments, portal, reports, mobile, expenses) |
| feature_request | Asks for something the product doesn't do |
| integration | QuickBooks, Xero, calendars, Zapier, API |
| data_import | Importing or exporting data (CSV import, full export) |
| cancellation | Wants to cancel or close the account |
| spam | Not a real support request (sales pitches, SEO offers, phishing, gibberish) |

When a ticket genuinely fits two categories, the second goes in `alt_category` and either one counts.
A `note` explains any label that might look surprising.

**queue** is not labeled. Code routes by category, like assignment rules in a CRM:
billing → Billing; access, how_to → Tier 1; bug, integration, data_import → Technical;
feature_request, cancellation → Account Management; spam → Spam Review.

**urgency**
- `urgent`: work is stopped for many people, money is moving wrongly (double charges, missing payouts),
  possible security problem, data loss, or a legal threat.
- `low`: feature requests, general questions with no deadline, spam.
- `normal`: everything else.

**resolution**
- `auto`: one help-center article fully answers it and nothing needs a human. Gold names the article
  (`kb_id`) and `required_facts`: short strings a correct reply must contain. Alternatives are
  separated by `|` (e.g. `"60 minutes|1 hour"`). Matching ignores case. An auto reply counts as
  correct when every required fact appears; whether it cited the same article is reported separately.
- `escalate`: a human must act or decide. Always escalate: cancellations, refund requests, legal
  threats, security reports, outages or data loss, urgent tickets, bugs (support must reproduce
  them), anything needing a change only staff can make, and tickets with two or more separate asks
  that no single article covers.
- `spam`: no reply; goes to Spam Review.

## Surveys

**themes** (zero or more; tag what the comment actually talks about)
onboarding, billing_pricing, support_speed, bugs_reliability, missing_feature, integrations,
ease_of_use, performance, mobile, praise_staff.

**sentiment**: `positive`, `negative`, or `mixed` (clearly both). Comments with no opinion
("n/a", "no comment") are `neutral`.

**follow_up**: `true` when someone should contact the customer: a churn signal ("looking at
other tools", "cancel at renewal"), an unresolved problem the customer is still stuck on, or a
detractor (0–6) with a specific, fixable complaint. Promoters asking for nothing are `false`.

*Clarified after the analyzer's v1 run (the gold labels didn't change):* "specific, fixable complaint" means
a problem with this customer's own account or work (wrong charge, missing money, something broken that blocks
them, an open ticket). Feature wishes and general opinions are product feedback, not follow-ups, unless the
customer also shows a churn signal or is stuck waiting on us. The v1 wording was loose enough that the model
read feature wishes as follow-ups, and that reading was fair.
