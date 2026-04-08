"""Auto-generate Ad Combos from Meta Ads — each ad name = 1 combo."""
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.adaccount import AdAccount as FBAdAccount

from app.database import SessionLocal
from app.models.account import AdAccount
from app.models.ad_angle import AdAngle
from app.models.ad_combo import AdCombo
from app.models.ad_copy import AdCopy
from app.models.ad_material import AdMaterial
from app.models.keypoint import BranchKeypoint  # ensure table is registered
from app.services.creative_service import next_combo_id

db = SessionLocal()

# Clear existing combos
db.query(AdCombo).delete()
db.commit()
print("Cleared existing combos")

accounts = db.query(AdAccount).filter(AdAccount.is_active.is_(True)).all()

# Build maps: copy_id by (branch_id, headline_prefix), material_id by (branch_id, description)
all_copies = db.query(AdCopy).all()
all_materials = db.query(AdMaterial).all()

# Map materials by description (ad name) + branch
mat_by_desc = {}
for m in all_materials:
    key = (m.branch_id, m.description)
    mat_by_desc[key] = m.material_id

# Map copies by branch_id — we'll match by order (copy N ↔ material N per branch)
copies_by_branch = {}
for c in all_copies:
    copies_by_branch.setdefault(c.branch_id, []).append(c)

mats_by_branch = {}
for m in all_materials:
    mats_by_branch.setdefault(m.branch_id, []).append(m)

combo_count = 0
seen_ad_names = set()

for acc in accounts:
    if not acc.access_token_enc:
        continue

    acc_id = acc.account_id if acc.account_id.startswith('act_') else f'act_{acc.account_id}'
    print(f"\n{'='*50}")
    print(f"{acc.account_name}")

    try:
        FacebookAdsApi.init(app_id='', app_secret='', access_token=acc.access_token_enc)
        fb_account = FBAdAccount(acc_id)

        ads = fb_account.get_ads(
            fields=['name', 'status', 'creative{title,body,thumbnail_url}', 'campaign{name}'],
            params={
                'limit': 100,
                'filtering': [{'field': 'ad.effective_status', 'operator': 'IN', 'value': ['ACTIVE', 'PAUSED']}],
            },
        )

        branch_copies = copies_by_branch.get(acc.id, [])
        branch_mats = mats_by_branch.get(acc.id, [])

        for ad in ads:
            ad_name = ad.get('name', '')
            if not ad_name:
                continue

            # Deduplicate by ad_name + branch
            dedup_key = (acc.id, ad_name)
            if dedup_key in seen_ad_names:
                continue
            seen_ad_names.add(dedup_key)

            creative = ad.get('creative', {})
            thumb = creative.get('thumbnail_url', '')

            # Find matching material (by description = ad_name)
            mat_id = mat_by_desc.get((acc.id, ad_name))
            if not mat_id and branch_mats:
                # Fallback: use first available material for this branch
                mat_id = branch_mats[0].material_id

            # Find matching copy (by headline match or fallback)
            title = creative.get('title', '')
            copy_id = None
            if title:
                for c in branch_copies:
                    if c.headline and title[:30] in c.headline:
                        copy_id = c.copy_id
                        break
            if not copy_id and branch_copies:
                # Match by body text snippet
                body = creative.get('body', '')
                if body:
                    for c in branch_copies:
                        if c.body_text and body[:50] in c.body_text:
                            copy_id = c.copy_id
                            break
            if not copy_id and branch_copies:
                copy_id = branch_copies[0].copy_id

            if not copy_id or not mat_id:
                continue

            cid = next_combo_id(db)
            combo = AdCombo(
                combo_id=cid,
                branch_id=acc.id,
                ad_name=ad_name,
                copy_id=copy_id,
                material_id=mat_id,
                verdict='TEST',
                verdict_source='auto',
            )
            db.add(combo)
            db.flush()
            combo_count += 1
            print(f"  {cid} = {ad_name[:55]}")

    except Exception as e:
        print(f"  ERROR: {e}")

db.commit()
db.close()
print(f"\n{'='*50}")
print(f"DONE! Created {combo_count} combos from Meta ads")
