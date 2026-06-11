"""Sync ad-level metrics from Meta into ad_combos table.

A combo is defined as a unique ad_name within a branch. Multiple Meta ads can
share the same name (different ad_ids) — their metrics are SUMMED into one combo.
"""
import sys, io, os
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.adaccount import AdAccount as FBAdAccount

from app.database import SessionLocal
from app.models.account import AdAccount
from app.models.ad_angle import AdAngle  # noqa: F401
from app.models.ad_combo import AdCombo
from app.models.ad_copy import AdCopy  # noqa: F401
from app.models.ad_material import AdMaterial  # noqa: F401
from app.models.campaign import Campaign  # noqa: F401
from app.models.keypoint import BranchKeypoint  # noqa: F401

db = SessionLocal()
accounts = db.query(AdAccount).filter(AdAccount.is_active.is_(True)).all()

INSIGHT_FIELDS = [
    'ad_name', 'spend', 'impressions', 'clicks',
    'actions', 'action_values',
    'video_thruplay_watched_actions', 'video_p100_watched_actions',
    'video_play_actions', 'inline_post_engagement',
]

TIME_RANGE = {'since': '2025-06-01', 'until': '2026-04-14'}


def is_purchase(action_type: str) -> bool:
    """Use omni_purchase only — Meta's unified, pre-deduped purchase metric
    that combines pixel + onsite + in-store + app purchases."""
    return action_type == 'omni_purchase'


def _first_value(arr):
    """Pull integer value from Meta's [{'action_type':..., 'value':...}] list."""
    if not arr:
        return 0
    try:
        return int(arr[0].get('value', 0))
    except (KeyError, ValueError, TypeError):
        return 0


total_combos_updated = 0

for acc in accounts:
    if acc.platform != 'meta' or not acc.access_token_enc:
        continue

    acc_id = acc.account_id if acc.account_id.startswith('act_') else f'act_{acc.account_id}'
    print(f"\n{'='*60}")
    print(f"{acc.account_name}")

    # Aggregator: (branch_id, ad_name) -> totals dict
    agg = defaultdict(lambda: {
        'spend': 0.0, 'impressions': 0, 'clicks': 0,
        'conversions': 0, 'revenue': 0.0, 'engagement': 0,
        'video_plays': 0, 'video_3s': 0, 'thruplay': 0, 'video_p100': 0,
    })

    try:
        FacebookAdsApi.init(app_id='', app_secret='', access_token=acc.access_token_enc)
        fb = FBAdAccount(acc_id)

        ads = fb.get_ads(
            fields=['name'],
            params={'limit': 500, 'filtering': [
                {'field': 'ad.effective_status', 'operator': 'IN',
                 'value': ['ACTIVE', 'PAUSED', 'ARCHIVED']},
            ]},
        )

        ad_count = 0
        for ad in ads:
            ad_name = ad.get('name', '')
            if not ad_name:
                continue
            ad_count += 1

            try:
                insights = ad.get_insights(fields=INSIGHT_FIELDS, params={'time_range': TIME_RANGE})
            except Exception:
                continue

            for row in insights:
                bucket = agg[ad_name]
                bucket['spend'] += float(row.get('spend', 0))
                bucket['impressions'] += int(row.get('impressions', 0))
                bucket['clicks'] += int(row.get('clicks', 0))
                bucket['engagement'] += int(row.get('inline_post_engagement', 0))

                for a in row.get('actions') or []:
                    if is_purchase(a.get('action_type', '')):
                        bucket['conversions'] += int(a.get('value', 0))
                    # video_view = 3-second plays (Ads Manager Hook rate numerator),
                    # NOT video_play_actions which counts every autoplay start.
                    elif a.get('action_type') == 'video_view':
                        bucket['video_3s'] += int(a.get('value', 0))
                for av in row.get('action_values') or []:
                    if is_purchase(av.get('action_type', '')):
                        bucket['revenue'] += float(av.get('value', 0))

                bucket['video_plays'] += _first_value(row.get('video_play_actions'))
                bucket['thruplay'] += _first_value(row.get('video_thruplay_watched_actions'))
                bucket['video_p100'] += _first_value(row.get('video_p100_watched_actions'))

        print(f"  Fetched {ad_count} ads, aggregated into {len(agg)} unique ad_names")

        # Apply aggregated metrics to combos
        applied = 0
        for ad_name, m in agg.items():
            combo = db.query(AdCombo).filter(
                AdCombo.branch_id == acc.id,
                AdCombo.ad_name == ad_name,
            ).first()
            if not combo:
                continue

            spend = m['spend']
            impressions = m['impressions']
            clicks = m['clicks']
            conversions = m['conversions']
            revenue = m['revenue']
            engagement = m['engagement']
            video_plays = m['video_plays']
            video_3s = m['video_3s']
            thruplay = m['thruplay']
            video_p100 = m['video_p100']

            combo.spend = spend
            combo.impressions = impressions
            combo.clicks = clicks
            combo.conversions = conversions
            combo.revenue = revenue
            combo.engagement = engagement
            combo.video_plays = video_plays or None
            combo.thruplay = thruplay or None
            combo.video_p100 = video_p100 or None

            # Recomputed rates from aggregated totals
            combo.roas = (revenue / spend) if spend > 0 else 0
            combo.cost_per_purchase = (spend / conversions) if conversions > 0 else None
            combo.ctr = (clicks / impressions) if impressions > 0 else None
            combo.engagement_rate = (engagement / impressions) if impressions > 0 else None
            combo.hook_rate = (video_3s / impressions) if video_3s and impressions > 0 else None
            combo.thruplay_rate = (thruplay / video_plays) if thruplay and video_plays > 0 else None
            combo.video_complete_rate = (video_p100 / video_plays) if video_p100 and video_plays > 0 else None

            applied += 1
            roas_str = f"{combo.roas:.2f}x" if combo.roas else "—"
            cpp_str = f"{float(combo.cost_per_purchase):,.0f}" if combo.cost_per_purchase else "—"
            print(f"  {combo.combo_id} | spend={spend:>10,.0f} | conv={conversions:>3} | ROAS={roas_str:>7s} | CPP={cpp_str:>10s} | {ad_name[:50]}")

        total_combos_updated += applied
        print(f"  Applied to {applied}/{len(agg)} combos in DB")

    except Exception as e:
        print(f"  ERROR: {e}")

db.commit()
db.close()
print(f"\n{'='*60}")
print(f"DONE! Total combos updated: {total_combos_updated}")
