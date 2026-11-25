"""
Alen Security - structured Google Ads pull (READ-ONLY).

Ported from the Hermes box script alen_ads_structured.py (Nov 2026 handoff bundle).
Changes versus the source:
1. Credentials from the environment, not a key file:
     GOOGLE_ADS_SA_JSON / GOOGLE_ADS_DEV_TOKEN  (workspace secrets)
     GOOGLE_ADS_MCC_ID (default 1614121172), GOOGLE_ADS_CID (default 4563394098)
2. Returns CSVs as strings; no writes to disk.
3. Adds checks Hermes ran via alen_ads_state2.py / alen_ads_structure.py (not in the
   bundle): network settings flags on campaigns, conversion split by action name,
   impression share with budget-lost/rank-lost, positive vs negative keywords,
   shared negative sets + attachments.

Every extra query degrades gracefully: failures are recorded in `errors` and surfaced
in the brief, never silently dropped.
"""
import csv
import io
import json
import os
import collections

from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException
from google.oauth2 import service_account

MCC_ID = os.environ.get("GOOGLE_ADS_MCC_ID", "1614121172")
CID = os.environ.get("GOOGLE_ADS_CID", "4563394098")
DEV_TOKEN = os.environ.get("GOOGLE_ADS_DEV_TOKEN", "")


def _n(v):
    try:
        return v.name
    except AttributeError:
        return str(v).split(".")[-1]


def _csv(header, rows):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(header)
    w.writerows(rows)
    return out.getvalue()


def build_client():
    sa_info = json.loads(os.environ["GOOGLE_ADS_SA_JSON"])
    creds = service_account.Credentials.from_service_account_info(
        sa_info, scopes=["https://www.googleapis.com/auth/adwords"])
    return GoogleAdsClient(credentials=creds, developer_token=DEV_TOKEN,
                           login_customer_id=MCC_ID, use_proto_plus=True)


def q(ga, query, label, errors):
    try:
        return list(ga.search(customer_id=CID, query=query))
    except GoogleAdsException as e:
        msg = "; ".join("[{}] {}".format(err.error_code, err.message[:150])
                        for err in e.failure.errors)
        errors.append("{}: {}".format(label, msg))
        return []


def pull(ga, start, end):
    errors = []
    out = {"window": {"start": start, "end": end}, "errors": errors}

    camps = q(ga, """SELECT campaign.id, campaign.name, campaign.status,
                            campaign.primary_status, campaign.advertising_channel_type,
                            campaign.advertising_channel_sub_type,
                            campaign.bidding_strategy_type, campaign.serving_status,
                            campaign.network_settings.target_search_network,
                            campaign.network_settings.target_content_network,
                            campaign.campaign_budget
                     FROM campaign ORDER BY campaign.name""", "inventory", errors)
    budgets = q(ga, """SELECT campaign_budget.resource_name, campaign_budget.amount_micros
                       FROM campaign_budget""", "budgets", errors)
    bmap = {b.campaign_budget.resource_name: b.campaign_budget.amount_micros / 1e6
            for b in budgets}

    out["campaigns"] = _csv(
        ["campaign_id", "name", "status", "primary_status", "channel_type", "sub_type",
         "bid_strategy", "serving_status", "display_network", "search_partners", "daily_budget"],
        [[c.id, c.name, _n(c.status), _n(c.primary_status), _n(c.advertising_channel_type),
          _n(c.advertising_channel_sub_type), _n(c.bidding_strategy_type), _n(c.serving_status),
          getattr(c.network_settings, "target_content_network", False),
          getattr(c.network_settings, "target_search_network", False),
          bmap.get(c.campaign_budget, "")]
         for c in (r.campaign for r in camps)])

    cg = q(ga, """SELECT campaign.id, campaign.name, campaign.status,
                         campaign_conversion_goal.category,
                         campaign_conversion_goal.origin,
                         campaign_conversion_goal.biddable
                  FROM campaign_conversion_goal ORDER BY campaign.name""", "conversion goals", errors)
    out["conversion_goals"] = _csv(
        ["campaign_id", "campaign", "campaign_status", "category", "origin", "biddable"],
        [[r.campaign.id, r.campaign.name, _n(r.campaign.status),
          _n(r.campaign_conversion_goal.category), _n(r.campaign_conversion_goal.origin),
          r.campaign_conversion_goal.biddable] for r in cg])

    monthly = q(ga, """SELECT campaign.id, campaign.name, campaign.advertising_channel_type,
                               segments.month, metrics.impressions, metrics.clicks,
                               metrics.cost_micros, metrics.conversions,
                               metrics.conversions_value, metrics.all_conversions
                        FROM campaign
                        WHERE segments.date BETWEEN '{}' AND '{}' """.format(start, end),
                "perf monthly", errors)
    out["performance_monthly"] = _csv(
        ["campaign_id", "campaign", "month", "impressions", "clicks", "cost",
         "conversions", "conv_value", "all_conversions"],
        [[r.campaign.id, r.campaign.name, r.segments.month, r.metrics.impressions,
          r.metrics.clicks, round(r.metrics.cost_micros / 1e6, 2),
          round(r.metrics.conversions, 2), round(r.metrics.conversions_value, 2),
          round(r.metrics.all_conversions, 2)] for r in monthly])

    daily = q(ga, """SELECT campaign.id, campaign.name, segments.date,
                            metrics.impressions, metrics.clicks, metrics.cost_micros,
                            metrics.conversions, metrics.conversions_value
                     FROM campaign
                     WHERE segments.date BETWEEN '{}' AND '{}' """.format(start, end),
              "perf daily", errors)
    drows = [[r.campaign.id, r.campaign.name, r.segments.date, r.metrics.impressions,
              r.metrics.clicks, round(r.metrics.cost_micros / 1e6, 2),
              round(r.metrics.conversions, 2), round(r.metrics.conversions_value, 2)]
             for r in daily]
    out["performance_daily"] = _csv(
        ["campaign_id", "campaign", "date", "impressions", "clicks", "cost",
         "conversions", "conv_value"], sorted(drows, key=lambda x: (x[2], x[1])))

    ags = q(ga, """SELECT campaign.id, campaign.name, ad_group.id, ad_group.name,
                           ad_group.status, ad_group.type, ad_group.cpc_bid_micros,
                           metrics.impressions, metrics.clicks, metrics.cost_micros,
                           metrics.conversions, metrics.conversions_value
                    FROM ad_group
                    WHERE segments.date BETWEEN '{}' AND '{}' """.format(start, end),
            "ad groups", errors)
    out["adgroups"] = _csv(
        ["campaign_id", "campaign", "ad_group_id", "ad_group", "status", "type",
         "cpc_bid", "impressions", "clicks", "cost", "conversions"],
        [[r.campaign.id, r.campaign.name, r.ad_group.id, r.ad_group.name,
          _n(r.ad_group.status), _n(r.ad_group.type),
          round(r.ad_group.cpc_bid_micros / 1e6, 2) if r.ad_group.cpc_bid_micros else "",
          r.metrics.impressions, r.metrics.clicks,
          round(r.metrics.cost_micros / 1e6, 2), round(r.metrics.conversions, 2)] for r in ags])

    ads = q(ga, """SELECT campaign.name, ad_group.name, ad_group_ad.ad.id,
                          ad_group_ad.status, ad_group_ad.policy_summary.approval_status,
                          ad_group_ad.ad.responsive_search_ad.headlines,
                          ad_group_ad.ad.responsive_search_ad.descriptions,
                          ad_group_ad.ad.responsive_search_ad.path1,
                          ad_group_ad.ad.responsive_search_ad.path2,
                          ad_group_ad.ad.final_urls
                   FROM ad_group_ad
                   WHERE ad_group_ad.ad.type = 'RESPONSIVE_SEARCH_AD'""", "ads (RSA)", errors)
    out["ads"] = _csv(
        ["campaign", "ad_group", "ad_id", "status", "approval", "headlines",
         "descriptions", "path1", "path2", "final_url"],
        [[r.campaign.name, r.ad_group.name, r.ad_group_ad.ad.id, _n(r.ad_group_ad.status),
          _n(r.ad_group_ad.policy_summary.approval_status),
          " | ".join(h.text for h in r.ad_group_ad.ad.responsive_search_ad.headlines),
          " | ".join(d.text for d in r.ad_group_ad.ad.responsive_search_ad.descriptions),
          r.ad_group_ad.ad.responsive_search_ad.path1,
          r.ad_group_ad.ad.responsive_search_ad.path2,
          (r.ad_group_ad.ad.final_urls[0] if r.ad_group_ad.ad.final_urls else "")]
         for r in ads])

    st = q(ga, """SELECT search_term_view.search_term, search_term_view.status,
                          campaign.name, campaign.advertising_channel_type,
                          ad_group.name, metrics.impressions, metrics.clicks,
                          metrics.cost_micros, metrics.conversions,
                          metrics.conversions_value
                   FROM search_term_view
                   WHERE segments.date BETWEEN '{}' AND '{}' """.format(start, end),
            "search terms", errors)
    srows = [[r.search_term_view.search_term, _n(r.search_term_view.status),
              r.campaign.name, _n(r.campaign.advertising_channel_type), r.ad_group.name,
              r.metrics.impressions, r.metrics.clicks,
              round(r.metrics.cost_micros / 1e6, 2), round(r.metrics.conversions, 2),
              round(r.metrics.conversions_value, 2)] for r in st]
    srows.sort(key=lambda x: -x[7])
    out["search_terms"] = _csv(
        ["search_term", "status", "campaign", "channel", "ad_group", "impressions",
         "clicks", "cost", "conversions", "conv_value"], srows)

    geo = q(ga, """SELECT campaign.name, geographic_view.country_criterion_id,
                          geographic_view.location_type, metrics.impressions,
                          metrics.clicks, metrics.cost_micros, metrics.conversions
                   FROM geographic_view
                   WHERE segments.date BETWEEN '{}' AND '{}' """.format(start, end),
            "geo", errors)
    out["geo"] = _csv(
        ["campaign", "geo_criterion", "location_type", "impressions", "clicks",
         "cost", "conversions"],
        [[r.campaign.name, r.geographic_view.country_criterion_id,
          _n(r.geographic_view.location_type), r.metrics.impressions, r.metrics.clicks,
          round(r.metrics.cost_micros / 1e6, 2), round(r.metrics.conversions, 2)] for r in geo])

    dev = q(ga, """SELECT campaign.name, segments.device, metrics.impressions,
                          metrics.clicks, metrics.cost_micros, metrics.conversions
                   FROM campaign
                   WHERE segments.date BETWEEN '{}' AND '{}' """.format(start, end),
            "device", errors)
    out["device"] = _csv(
        ["campaign", "device", "impressions", "clicks", "cost", "conversions"],
        [[r.campaign.name, _n(r.segments.device), r.metrics.impressions, r.metrics.clicks,
          round(r.metrics.cost_micros / 1e6, 2), round(r.metrics.conversions, 2)] for r in dev])

    ca = q(ga, """SELECT conversion_action.id, conversion_action.name,
                         conversion_action.status, conversion_action.type,
                         conversion_action.category, conversion_action.primary_for_goal,
                         conversion_action.include_in_conversions_metric,
                         conversion_action.counting_type,
                         conversion_action.click_through_lookback_window_days
                  FROM conversion_action ORDER BY conversion_action.name""",
           "conversion actions", errors)
    out["conversion_actions"] = _csv(
        ["id", "name", "status", "type", "category", "primary_for_goal",
         "included_in_conv_metric", "counting", "click_lookback_days"],
        [[r.conversion_action.id, r.conversion_action.name, _n(r.conversion_action.status),
          _n(r.conversion_action.type), _n(r.conversion_action.category),
          r.conversion_action.primary_for_goal,
          r.conversion_action.include_in_conversions_metric,
          _n(r.conversion_action.counting_type),
          r.conversion_action.click_through_lookback_window_days] for r in ca])

    # ---- extras Hermes ran via state2/structure scripts ---------------------
    cba = q(ga, """SELECT campaign.name, segments.conversion_action_name,
                          segments.date, metrics.conversions, metrics.conversions_value
                   FROM campaign
                   WHERE segments.date BETWEEN '{}' AND '{}' """.format(start, end),
            "conv by action", errors)
    agg = collections.defaultdict(lambda: [0, 0.0])
    for r in cba:
        k = (r.campaign.name, r.segments.conversion_action_name)
        agg[k][0] += r.metrics.conversions
        agg[k][1] += r.metrics.conversions_value
    out["conv_by_action"] = _csv(
        ["campaign", "conversion_action", "conversions", "conv_value"],
        [[k[0], k[1], round(v[0], 2), round(v[1], 2)] for k, v in agg.items()])

    ish = q(ga, """SELECT campaign.name, metrics.search_impression_share,
                          metrics.search_budget_lost_impression_share,
                          metrics.search_rank_lost_impression_share,
                          metrics.impressions, metrics.cost_micros
                   FROM campaign
                   WHERE segments.date BETWEEN '{}' AND '{}' """.format(start, end),
            "impression share", errors)
    out["impression_share"] = _csv(
        ["campaign", "search_is", "budget_lost_is", "rank_lost_is", "impressions", "cost"],
        [[r.campaign.name,
          round(r.metrics.search_impression_share, 4) if r.metrics.search_impression_share else "",
          round(r.metrics.search_budget_lost_impression_share, 4) if r.metrics.search_budget_lost_impression_share else "",
          round(r.metrics.search_rank_lost_impression_share, 4) if r.metrics.search_rank_lost_impression_share else "",
          r.metrics.impressions, round(r.metrics.cost_micros / 1e6, 2)] for r in ish])

    kw = q(ga, """SELECT campaign.name, ad_group.name, ad_group_criterion.keyword.text,
                         ad_group_criterion.negative, ad_group_criterion.status, ad_group_criterion.type
                  FROM ad_group_criterion
                  WHERE ad_group_criterion.status IN ('ENABLED') ORDER BY campaign.name""",
           "keywords", errors)
    out["keywords"] = _csv(
        ["campaign", "ad_group", "keyword", "negative", "status", "type"],
        [[r.campaign.name, r.ad_group.name, r.ad_group_criterion.keyword.text,
          r.ad_group_criterion.negative, _n(r.ad_group_criterion.status),
          _n(r.ad_group_criterion.type)] for r in kw])

    ss = q(ga, """SELECT shared_set.id, shared_set.name, shared_set.status, shared_set.type
                   FROM shared_set WHERE shared_set.type = 'NEGATIVE_KEYWORDS'""",
           "shared sets", errors)
    out["shared_sets"] = _csv(
        ["set_id", "name", "status", "type"],
        [[r.shared_set.id, r.shared_set.name, _n(r.shared_set.status), _n(r.shared_set.type)]
         for r in ss])

    sc = q(ga, """SELECT shared_set.name, shared_criterion.keyword.text
                  FROM shared_criterion""", "shared criteria", errors)
    out["shared_criteria"] = _csv(
        ["shared_set", "keyword"],
        [[r.shared_set.name, r.shared_criterion.keyword.text] for r in sc])

    ccs = q(ga, """SELECT campaign_shared_set.campaign, shared_set.name
                   FROM campaign_shared_set""", "campaign shared sets", errors)
    out["campaign_shared_sets"] = _csv(
        ["campaign_resource", "shared_set"],
        [[r.campaign_shared_set.campaign, r.shared_set.name] for r in ccs])

    # ---- summary + reconciliation (as the Hermes script) -------------------
    tot = collections.defaultdict(float)
    for r in daily:
        tot["cost"] += r.metrics.cost_micros / 1e6
        tot["clicks"] += r.metrics.clicks
        tot["impr"] += r.metrics.impressions
        tot["conv"] += r.metrics.conversions
        tot["convval"] += r.metrics.conversions_value
    item = collections.defaultdict(lambda: [0, 0.0, 0.0])
    for r in st:
        a = item[_n(r.campaign.advertising_channel_type)]
        a[0] += r.metrics.clicks
        a[1] += r.metrics.cost_micros / 1e6
        a[2] += r.metrics.conversions
    summary = {
        "customer_id": CID, "window": {"start": start, "end": end},
        "account": {k: round(v, 2) for k, v in tot.items()},
        "itemized_search_terms": {k: {"clicks": v[0], "cost": round(v[1], 2),
                                      "conversions": v[2]} for k, v in item.items()},
        "no_query_detail": {
            "clicks": tot["clicks"] - sum(v[0] for v in item.values()),
            "cost": round(tot["cost"] - sum(v[1] for v in item.values()), 2),
            "pct_of_spend": round(100 * (tot["cost"] - sum(v[1] for v in item.values())) / tot["cost"], 1) if tot["cost"] else 0,
        },
        "campaign_count": len(camps),
        "campaigns_enabled": sum(1 for r in camps if _n(r.campaign.status) == "ENABLED"),
        "campaigns_primary_ended": [r.campaign.name for r in camps if _n(r.campaign.primary_status) == "ENDED"],
        "campaigns_zero_spend": sorted({r.campaign.name for r in camps} -
                                      {r.campaign.name for r in daily if r.metrics.cost_micros > 0}),
    }
    out["summary_text"] = json.dumps(summary, indent=2)
    return out
