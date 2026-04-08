"""Sync ad-level metrics from Meta into ad_combos table."""
import sys, io, os
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
    'ad_name', 'spend', 'impressions', 'clicks', 'ctr',
    'actions', 'action_values', 'cost_per_action_type',
    'video_thruplay_watched_actions', 'video_p100_watched_actions',
    'video_play_actions', 'inline_post_engagement',
]

PURCHASE_TYPES = {'purchase', 'offsite_conversion.fb_pixel_purchase'}
updated = 0

for acc in accounts:
    if not acc.access_token_enc:
        continue

    acc_id = acc.account_id if acc.account_id.startswith('act_') else f'act_{acc.account_id}'
    print(f"\n{'='*50}")
    print(f"{acc.account_name}")

    try:
        FacebookAdsApi.init(app_id='', app_secret='', access_token=acc.access_token_enc)
        fb = FBAdAccount(acc_id)

        ads = fb.get_ads(
            fields=['name'],
            params={'limit': 200, 'filtering': [
                {'field': 'ad.effective_status', 'operator': 'IN', 'value': ['ACTIVE', 'PAUSED']},
            ]},
        )

        for ad in ads:
            ad_name = ad.get('name', '')
            if not ad_name:
                continue

            # Find matching combo
            combo = db.query(AdCombo).filter(
                AdCombo.branch_id == acc.id,
                AdCombo.ad_name == ad_name,
            ).first()
            if not combo:
                continue

            # Fetch insights (last 30 days for meaningful data)
            try:
                insights = ad.get_insights(fields=INSIGHT_FIELDS, params={'date_preset': 'last_30d'})
            except Exception:
                continue

            for row in insights:
                spend = float(row.get('spend', 0))
                impressions = int(row.get('impressions', 0))
                clicks = int(row.get('clicks', 0))
                ctr = float(row.get('ctr', 0))
                engagement = int(row.get('inline_post_engagement', 0))

                # Parse purchase conversions + revenue
                conversions = 0
                revenue = 0.0
                actions = row.get('actions') or []
                action_values = row.get('action_values') or []
                cost_per_actions = row.get('cost_per_action_type') or []

                for a in actions:
                    if a.get('action_type') in PURCHASE_TYPES:
                        conversions += int(a.get('value', 0))
                for av in action_values:
                    if av.get('action_type') in PURCHASE_TYPES:
                        revenue += float(av.get('value', 0))

                cost_per_purchase = None
                for cpa in cost_per_actions:
                    if cpa.get('action_type') in PURCHASE_TYPES:
                        cost_per_purchase = float(cpa.get('value', 0))
                        break

                # Video metrics
                video_plays_raw = row.get('video_play_actions') or []
                thruplay_raw = row.get('video_thruplay_watched_actions') or []
                p100_raw = row.get('video_p100_watched_actions') or []

                video_plays = int(video_plays_raw[0]['value']) if video_plays_raw else None
                thruplay = int(thruplay_raw[0]['value']) if thruplay_raw else None
                video_p100 = int(p100_raw[0]['value']) if p100_raw else None

                # Computed rates
                roas = revenue / spend if spend > 0 else 0
                engagement_rate = engagement / impressions if impressions > 0 else 0
                hook_rate = video_plays / impressions if video_plays and impressions > 0 else None
                thruplay_rate = thruplay / video_plays if thruplay and video_plays and video_plays > 0 else None
                video_complete_rate = video_p100 / video_plays if video_p100 and video_plays and video_plays > 0 else None

                # Update combo
                combo.spend = spend
                combo.impressions = impressions
                combo.clicks = clicks
                combo.conversions = conversions
                combo.revenue = revenue
                combo.roas = roas
                combo.ctr = ctr / 100  # Meta returns % as 1.64, store as 0.0164
                combo.cost_per_purchase = cost_per_purchase
                combo.engagement = engagement
                combo.engagement_rate = engagement_rate
                combo.video_plays = video_plays
                combo.thruplay = thruplay
                combo.video_p100 = video_p100
                combo.hook_rate = hook_rate
                combo.thruplay_rate = thruplay_rate
                combo.video_complete_rate = video_complete_rate

                updated += 1
                roas_str = f"{roas:.2f}x" if roas else "—"
                hook_str = f"{hook_rate*100:.1f}%" if hook_rate else "—"
                print(f"  {combo.combo_id} | ROAS={roas_str:>7s} | CPP={cost_per_purchase or 0:>10,.0f} | Hook={hook_str:>6s} | {ad_name[:40]}")

    except Exception as e:
        print(f"  ERROR: {e}")

db.commit()
db.close()
print(f"\n{'='*50}")
print(f"DONE! Updated {updated} combos with real metrics")
