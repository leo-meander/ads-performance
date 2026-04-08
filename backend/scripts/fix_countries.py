"""Fix combo countries by pulling actual targeting from Meta adset."""
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.adaccount import AdAccount as FBAdAccount
from app.database import SessionLocal, engine
from app.models.account import AdAccount
from app.models.ad_combo import AdCombo
from app.models.ad_copy import AdCopy
from app.models.ad_material import AdMaterial
from app.models.ad_angle import AdAngle
from app.models.keypoint import BranchKeypoint
from app.models.campaign import Campaign
from sqlalchemy import text

db = SessionLocal()
accounts = db.query(AdAccount).filter(AdAccount.is_active.is_(True)).all()

# Build ad_name → country map from Meta
ad_countries = {}  # (branch_id, ad_name) → country code

for acc in accounts:
    if not acc.access_token_enc:
        continue
    acc_id = acc.account_id if acc.account_id.startswith('act_') else f'act_{acc.account_id}'
    print(f"\n{acc.account_name}")

    try:
        FacebookAdsApi.init(app_id='', app_secret='', access_token=acc.access_token_enc)
        fb = FBAdAccount(acc_id)
        ads = fb.get_ads(
            fields=['name', 'adset{name,targeting}'],
            params={'limit': 200, 'filtering': [
                {'field': 'ad.effective_status', 'operator': 'IN', 'value': ['ACTIVE', 'PAUSED']}
            ]},
        )

        for ad in ads:
            name = ad.get('name', '')
            adset = ad.get('adset', {})
            targeting = adset.get('targeting', {}) if adset else {}
            geo = targeting.get('geo_locations', {})
            countries = geo.get('countries', [])

            if countries:
                # Use first country, or join if multiple
                country = countries[0] if len(countries) == 1 else ','.join(sorted(countries))
            else:
                # Try to get from adset name
                adset_name = adset.get('name', '') if adset else ''
                country = None
                for code in ['PH', 'AU', 'US', 'UK', 'HK', 'SG', 'JP', 'TW', 'CN', 'CA', 'DE', 'ID', 'MY', 'KR', 'TH', 'VN']:
                    if f'_{code}_' in adset_name or adset_name.startswith(f'{code}_') or adset_name.endswith(f'_{code}'):
                        country = code
                        break
                if not country and 'All' in adset_name:
                    country = 'ALL'

            key = (acc.id, name)
            if key not in ad_countries or (country and country != 'ALL'):
                ad_countries[key] = country

            if country:
                print(f"  {name[:45]:45s} → {country}")

    except Exception as e:
        print(f"  ERROR: {e}")

# Update combos
updated = 0
with engine.connect() as c:
    combos = c.execute(text('SELECT id, branch_id, ad_name FROM ad_combos')).fetchall()
    for combo in combos:
        country = ad_countries.get((combo[1], combo[2]))
        if country:
            c.execute(text('UPDATE ad_combos SET country = :co WHERE id = :id'), {'co': country, 'id': combo[0]})
            updated += 1
    c.commit()

print(f"\nUpdated {updated} combos with real targeting countries")

# Stats
with engine.connect() as c:
    rows = c.execute(text('SELECT country, COUNT(*) FROM ad_combos WHERE country IS NOT NULL GROUP BY country ORDER BY COUNT(*) DESC')).fetchall()
    print("Country distribution:")
    for r in rows:
        print(f"  {r[0]:6s} = {r[1]}")

db.close()
