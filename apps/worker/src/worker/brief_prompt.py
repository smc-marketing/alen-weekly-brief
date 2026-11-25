"""
Brief prompt construction for the Alen Security weekly Google Ads brief.

The REPORT RULES below are the load-bearing field rules from the Hermes cron job
cb332bc38726, copied verbatim from the handoff bundle (not paraphrased).
Only the sections that referenced Hermes paths/scripts were adapted.
"""

REPORT_RULES = """Weekly Google Ads performance + health brief for ALEN SECURITY (a commercial security systems integrator selling $50K-$500K multi-site B2B projects). Delivered every Monday 7:30 AM US Eastern so Mike walks into the week prepared. Anchor every time reference to US Eastern (ET).

The Google Ads pull has ALREADY been executed by the workflow runtime. The datasets are embedded below. There are no scripts to run: treat the embedded CSVs and JSON as ground truth and process them IN FULL. If you did not process the whole file, write "not computed" - never estimate from a sample.

REPORT SECTIONS:
1. VERDICT - one line: healthy / needs work / critical, with the single most important number.
2. PERFORMANCE - this week vs last week: spend, impressions, clicks, CTR, conversions, CPA, conversion value. Per campaign: spend, clicks, conversions, CPA. Name the biggest mover.
3. HARD ALERTS (check every week, report every hit even if unchanged):
   - any campaign with status=ENABLED and primary_status=ENDED (it is not serving - that is how Alen lost its best campaign on Aug 31)
   - any campaign with $0 spend over the window, especially one carrying a large daily budget
   - budget utilization: sum of daily budgets vs delivered spend (the account has historically delivered ~12% of capacity)
   - conversions by action: calls vs forms. Alen has produced ZERO Search form conversions in four months - flag immediately if forms are still 0.
   - any ad with an empty headline, a malformed/fused final URL, or a policy status other than APPROVED
   - Display network (target_content_network) or Search Partners (target_search_network) turned back ON in any Search campaign (columns display_network / search_partners in campaigns.csv)
4. QUERY HYGIENE - tag the itemized search terms for the window into junk vs buyer buckets using this exact taxonomy:
   JUNK_Jobs (job, hiring, career, guard, officer, apply, recruiting), JUNK_Competitor (adt, allied universal, vector security, brinks, vivint, simplisafe, ring, frontpoint, alarm.com, securitas, wackenhut, garda...), JUNK_Locksmith (locksmith, pop a lock, cerrajero, rekey), JUNK_Spanish (seguridad, cerrajero, de seguridad), JUNK_Consumer (home, residential, apartment, doorbell, DIY camera brands hikvision/reolink/swann), BUYER_CloudAccess (cloud, brivo, eagle eye, access control, remote lock, managed), BUYER_Commercial (commercial security, office security, enterprise, retail, building), BUYER_Fire (fire alarm, ansul, suppression), BRAND_Alen (alen), Generic_Broad (bare "security", "camera", "surveillance").
   Collision rules: use word boundaries, never bare substring `in` (n-arrow security must not match "arrow security" as a mere substring of another word); keep only the most specific form of subsumed duplicates and re-total so roots sum back to the junk total.
   Report: rows, itemized spend, and the junk/buyer split AS A % OF THE STRIPPED ITEMIZED TOTAL. ALWAYS state the denominator and ALWAYS report the spend with no query-level detail (the embedded search_terms.csv is the API search_term_view pull: Search-channel rows only, NO PMax; historically only ~36% of spend is visible at query level - quote dataset B, never blend denominators). NEVER characterise waste from a partial read. Threshold: JUNK > 25% of spend = the #1 fix.
   Propose new negative root terms as a list for Mike to approve (phrase match) - and never propose blanket-excluding a term that carries a conversion. HOLD list - conversion-bearing competitor roots that must NOT be blanket-excluded: "vector security" ($113.87 / 1 conv), "narrow security" ($45.49 / 1), "maximal security" ($3.43 / 1).
5. STRUCTURE WATCH - confirm the five shared negative lists exist and are attached to all Search campaigns (Alen | Neg | Competitors / Consumer & DIY / Guard & Manpower / Job Seekers / Locksmith & Lockout) using shared_sets.csv, shared_criteria.csv and campaign_shared_sets.csv; note the three HELD conversion-bearing roots are still intentionally excluded; report the AREA_OF_INTEREST vs LOCATION_OF_PRESENCE spend split (geo.csv, location_type column) and flag if interest-only traffic exceeds 25% of spend.
6. NEXT 3 ACTIONS - ranked, specific, each naming the campaign/ad group term involved, and marked UI (Mike's) or API (bulk op on request).

CROSS-CHECK LENS (Lens B, high-ticket B2B - apply when judging the structure):
- Small budgets do not mean lead volume problems: at $1.5K-$2.5K/mo the account buys ~4-8 conversations/month. Strategy is precision + qualification, not volume.
- PMax is a supporting retargeting layer, NOT the lead engine for six-figure deals. Tightly-themed exact-match Search on high-intent buyer keywords is where real buyers live.
- Feed Conversion Value: if conv_value is exactly $1.00 per conversion, Smart Bidding is blind - flag it.
- Dead / zero-spend campaigns that look "Eligible" are a structural red flag: too-narrow keywords or caps that never enter auctions. Account-level constraints first (serving_status LIMITED with others ELIGIBLE at zero spend is the tell).
- GAQL Reading pitfalls that apply to these CSVs: status can be ENABLED while primary_status is ENDED (read both); impressions-share columns split budget-lost vs rank-lost; an ad_network CONTENT slice in a "Search" campaign is network settings leaking.

OUTPUT RULES:
- Telegram truncates long messages, the runtime handles splitting/attaching: write the full tight, data-first brief as your complete answer - punchy verdicts, specific numbers, no generic advice, no filler, no restating this prompt. Start with the VERDICT line.
- THIS JOB IS READ-ONLY. Never propose executing a mutation as part of the brief. Report what should change and let Mike decide; he owns UI changes; bulk API ops happen only on his explicit request, in a separate reviewed process.
"""


def _section(title, body):
    return "### " + title + "\n```\n" + (body if body else "(empty)") + "\n```\n"


def build_prompt(this, prev):
    """Assemble the full user message: rules + embedded datasets for both windows."""
    parts = [REPORT_RULES, ""]
    parts.append("DATASETS (API pull, read-only). THIS WEEK window: %(start)s .. %(end)s." % this["window"])

    # summary + reconciliations first - the model must read them before the CSVs
    parts.append(_section("summary.json THIS WEEK (account totals + reconciliations)",
                           this.get("summary_text", "{}")))
    parts.append(_section("campaigns.csv (includes network flags, serving_status, budgets)", this["campaigns"]))
    parts.append(_section("conversion_goals.csv (empty biddable set = blind bidding)", this["conversion_goals"]))
    parts.append(_section("performance_monthly.csv THIS WEEK", this["performance_monthly"]))
    parts.append(_section("performance_daily.csv THIS WEEK", this["performance_daily"]))
    parts.append(_section("conversion split by action name (conv_by_action.csv)", this.get("conv_by_action", "")))
    parts.append(_section("impression share (impression_share.csv)", this.get("impression_share", "")))
    parts.append(_section("ads.csv (RSA status + policy approval)", this["ads"]))
    parts.append(_section("search_terms.csv (API itemized, Search-channel only, ~36%% of spend)", this["search_terms"]))
    parts.append(_section("geo.csv (location_type: AREA_OF_INTEREST vs LOCATION_OF_PRESENCE)", this["geo"]))
    parts.append(_section("device.csv", this["device"]))
    parts.append(_section("conversion_actions.csv", this["conversion_actions"]))
    parts.append(_section("keywords.csv (positives and negatives, negative column)", this.get("keywords", "")))
    parts.append(_section("shared_sets.csv", this.get("shared_sets", "")))
    parts.append(_section("shared_criteria.csv", this.get("shared_criteria", "")))
    parts.append(_section("campaign_shared_sets.csv (attachments)", this.get("campaign_shared_sets", "")))

    parts.append("LAST WEEK window: %(start)s .. %(end)s - used only for week-over-week deltas in PERFORMANCE." % prev["window"])
    parts.append(_section("summary.json LAST WEEK", prev.get("summary_text", "{}")))
    parts.append(_section("performance_monthly.csv LAST WEEK", prev["performance_monthly"]))
    parts.append(_section("campaigns.csv LAST WEEK (budget/status cross-check)", prev["campaigns"]))

    if this.get("errors"):
        parts.append(_section("PULL WARNINGS (queries that failed - report these, never paper over)",
                             "\n".join(this["errors"])))
    return "\n".join(parts)
