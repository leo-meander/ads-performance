"""Seed Creative Library from REAL Meta Ads data (2026 ads)."""
import sys, io, os, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.adaccount import AdAccount as FBAdAccount

from app.database import SessionLocal
from app.models.account import AdAccount
from app.models.ad_angle import AdAngle
from app.models.ad_copy import AdCopy
from app.models.ad_material import AdMaterial
from app.models.keypoint import BranchKeypoint
from app.services.creative_service import next_angle_id, next_copy_id, next_material_id

db = SessionLocal()

# Clear old seeded data
db.query(AdCopy).delete()
db.query(AdMaterial).delete()
db.query(AdAngle).delete()
db.commit()
print("Cleared old creative data")

accounts = db.query(AdAccount).filter(AdAccount.is_active.is_(True)).all()

# ── Detect TA from ad/campaign name ──
def detect_ta(name: str) -> str:
    n = name.lower()
    if 'couple' in n or 'romantic' in n:
        return 'Couple'
    if 'friend' in n or 'group' in n:
        return 'Group'
    if 'family' in n:
        return 'Family'
    return 'Solo'

# ── Detect material type from ad name ──
def detect_material_type(name: str) -> str:
    n = name.lower()
    if '[video]' in n:
        return 'video'
    if '[carousel]' in n:
        return 'carousel'
    return 'image'

# ── Extract angle from campaign name ──
def extract_angle(campaign_name: str, ad_name: str) -> str:
    # Try to extract the key theme
    parts = []
    if 'sakura' in campaign_name.lower() or 'sakura' in ad_name.lower():
        parts.append('Sakura/Cherry blossom season')
    if 'landing page' in campaign_name.lower() or 'landing' in campaign_name.lower():
        parts.append('Direct booking landing page')
    if 'remarketing' in campaign_name.lower() or 'retarget' in campaign_name.lower():
        parts.append('Remarketing/Retargeting')
    if 'engagement' in campaign_name.lower() or 'engagment' in campaign_name.lower():
        parts.append('Engagement/Brand awareness')
    if 'reach' in campaign_name.lower():
        parts.append('Reach campaign')
    if 'kol' in ad_name.lower():
        parts.append('KOL/Influencer content')
    if 'ai_' in ad_name.lower():
        parts.append('AI-generated creative')
    if not parts:
        parts.append('General promotion')
    return ' + '.join(parts)

# Track unique angles to avoid duplicates
seen_angles = set()
copy_count = 0
material_count = 0
angle_count = 0

for acc in accounts:
    if not acc.access_token_enc:
        continue

    acc_id = acc.account_id if acc.account_id.startswith('act_') else f'act_{acc.account_id}'
    print(f"\n{'='*60}")
    print(f"Fetching ads from {acc.account_name} ({acc_id})")

    try:
        FacebookAdsApi.init(app_id='', app_secret='', access_token=acc.access_token_enc)
        fb_account = FBAdAccount(acc_id)

        ads = fb_account.get_ads(
            fields=['name', 'status', 'creative{title,body,call_to_action_type,thumbnail_url}', 'campaign{name}'],
            params={
                'limit': 100,
                'filtering': [{'field': 'ad.effective_status', 'operator': 'IN', 'value': ['ACTIVE', 'PAUSED']}],
            },
        )

        for ad in ads:
            ad_name = ad.get('name', '')
            campaign = ad.get('campaign', {})
            campaign_name = campaign.get('name', '')
            creative = ad.get('creative', {})
            status = ad.get('status', 'PAUSED')

            title = creative.get('title', '')
            body = creative.get('body', '')
            cta = creative.get('call_to_action_type', '')
            thumb = creative.get('thumbnail_url', '')

            ta = detect_ta(campaign_name + ' ' + ad_name)
            mat_type = detect_material_type(ad_name)

            # ── Create angle (deduplicated by campaign pattern) ──
            angle_key = f"{acc.id}_{ta}_{extract_angle(campaign_name, ad_name)}"
            if angle_key not in seen_angles:
                seen_angles.add(angle_key)
                aid = next_angle_id(db)
                angle_text = extract_angle(campaign_name, ad_name)
                db.add(AdAngle(
                    angle_id=aid,
                    branch_id=acc.id,
                    target_audience=ta,
                    angle_text=angle_text,
                    status='TEST',  # default, can be manually updated
                    notes=f"From campaign: {campaign_name}",
                ))
                db.flush()
                angle_count += 1

            # ── Create copy (if has title or body) ──
            if title or body:
                cid = next_copy_id(db)
                # Detect language
                lang = 'en'
                if any(ord(c) > 0x4E00 for c in (title + body)[:50]):
                    lang = 'zh'
                if any(ord(c) > 0x3040 and ord(c) < 0x30FF for c in (title + body)[:50]):
                    lang = 'ja'

                headline = title if title else ad_name
                body_text = body if body else f"[No body text — ad name: {ad_name}]"

                db.add(AdCopy(
                    copy_id=cid,
                    branch_id=acc.id,
                    target_audience=ta,
                    headline=headline[:500],
                    body_text=body_text,
                    cta=cta if cta else None,
                    language=lang,
                ))
                db.flush()
                copy_count += 1

            # ── Create material (if has thumbnail) ──
            if thumb:
                mid = next_material_id(db)
                db.add(AdMaterial(
                    material_id=mid,
                    branch_id=acc.id,
                    material_type=mat_type,
                    file_url=thumb,
                    description=ad_name,
                    target_audience=ta,
                ))
                db.flush()
                material_count += 1

            print(f"  {ad_name[:50]:50s} | {ta:6s} | {mat_type:8s} | {'has copy' if (title or body) else 'no copy'}")

    except Exception as e:
        print(f"  ERROR: {e}")

db.commit()
db.close()

print(f"\n{'='*60}")
print(f"DONE!")
print(f"  Angles:    {angle_count}")
print(f"  Copies:    {copy_count}")
print(f"  Materials: {material_count}")
