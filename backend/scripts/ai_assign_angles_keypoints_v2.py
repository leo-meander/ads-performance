"""Use AI to analyze ad copy text + thumbnail and assign angle + keypoints."""
import sys, io, os, json, base64, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from anthropic import Anthropic
from app.database import SessionLocal, engine
from app.models.account import AdAccount
from app.models.ad_angle import AdAngle
from app.models.ad_combo import AdCombo
from app.models.ad_copy import AdCopy
from app.models.ad_material import AdMaterial
from app.models.keypoint import BranchKeypoint
from app.models.campaign import Campaign
from sqlalchemy import text

db = SessionLocal()
client = Anthropic()

# Load all data
accounts = {a.id: a.account_name for a in db.query(AdAccount).all()}
keypoints = db.query(BranchKeypoint).filter(BranchKeypoint.is_active.is_(True)).all()
copies = {c.copy_id: c for c in db.query(AdCopy).all()}
materials = {m.material_id: m for m in db.query(AdMaterial).all()}

# Angles per branch
with engine.connect() as c:
    ang_rows = c.execute(text('SELECT angle_id, branch_id, angle_type, angle_explain FROM ad_angles')).fetchall()
angles_by_branch = {}
for r in ang_rows:
    angles_by_branch.setdefault(r[1], []).append({'angle_id': r[0], 'type': r[2], 'explain': (r[3] or '')[:80]})

# Keypoints per branch
kps_by_branch = {}
for kp in keypoints:
    kps_by_branch.setdefault(kp.branch_id, []).append({'id': kp.id, 'cat': kp.category, 'title': kp.title})

# Load combos
combos = db.query(AdCombo).all()
print(f'Total combos: {len(combos)}')

# Process in batches of 5 (with images, smaller batches)
BATCH = 5
updated = 0

for i in range(0, len(combos), BATCH):
    batch = combos[i:i+BATCH]
    print(f'\nBatch {i//BATCH+1} ({len(batch)} combos)')

    messages_content = []

    # Build text context
    combo_descriptions = []
    for combo in batch:
        copy = copies.get(combo.copy_id)
        mat = materials.get(combo.material_id)
        branch = accounts.get(combo.branch_id, '?')

        desc = {
            'combo_id': combo.combo_id,
            'branch': branch,
            'ad_name': combo.ad_name,
            'headline': copy.headline[:200] if copy else '',
            'body': copy.body_text[:300] if copy else '',
            'material_type': mat.material_type if mat else '',
        }
        combo_descriptions.append(desc)

        # Try to fetch thumbnail for vision
        if mat and mat.file_url and mat.file_url.startswith('http'):
            try:
                req = urllib.request.Request(mat.file_url, headers={'User-Agent': 'Mozilla/5.0'})
                resp = urllib.request.urlopen(req, timeout=5)
                img_data = resp.read()
                if len(img_data) < 5_000_000:  # max 5MB
                    b64 = base64.standard_b64encode(img_data).decode('utf-8')
                    content_type = resp.headers.get('Content-Type', 'image/jpeg')
                    if 'image' in content_type:
                        messages_content.append({
                            "type": "image",
                            "source": {"type": "base64", "media_type": content_type.split(';')[0], "data": b64}
                        })
                        messages_content.append({
                            "type": "text",
                            "text": f"[Thumbnail for {combo.combo_id} - {combo.ad_name}]"
                        })
            except Exception:
                pass  # skip if image fails

    # Available angles and keypoints for these branches
    branch_ids = list(set(c.branch_id for c in batch))
    available_angles = {}
    available_kps = {}
    for bid in branch_ids:
        available_angles[bid] = angles_by_branch.get(bid, [])
        available_kps[bid] = kps_by_branch.get(bid, [])

    prompt_text = f"""Analyze these hotel ad combos and assign the best matching ANGLE and KEYPOINTS for each.

COMBOS:
{json.dumps(combo_descriptions, ensure_ascii=False, indent=1)}

AVAILABLE ANGLES (per branch):
{json.dumps(available_angles, ensure_ascii=False, indent=1)}

AVAILABLE KEYPOINTS (per branch):
{json.dumps(available_kps, ensure_ascii=False, indent=1)}

For each combo, based on the ad copy text, headline, and thumbnail image (if provided):
1. Match the BEST angle by analyzing what hook/approach the ad uses
2. Match 1-3 keypoints that the ad highlights

Rules:
- Angle and keypoints MUST be from the same branch as the combo
- Look at the actual ad copy content to determine the approach
- KOL content that shows the property → match keypoints about what's shown
- If copy mentions location/distance → match location keypoints
- If copy mentions amenities → match amenity keypoints
- If copy mentions price/value → match value keypoints

Return ONLY JSON array:
[{{"combo_id": "CMB-001", "angle_id": "ANG-001", "keypoint_ids": ["uuid1", "uuid2"]}}]
No markdown."""

    messages_content.append({"type": "text", "text": prompt_text})

    try:
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            messages=[{"role": "user", "content": messages_content}],
        )
        raw = resp.content[0].text.strip()
        if raw.startswith('```'):
            raw = raw.split('\n', 1)[1].rsplit('```', 1)[0]

        assignments = json.loads(raw)

        with engine.connect() as c:
            for asgn in assignments:
                cid = asgn.get('combo_id')
                aid = asgn.get('angle_id')
                kpids = asgn.get('keypoint_ids', [])

                updates = {}
                if aid:
                    updates['angle_id'] = aid
                if kpids:
                    updates['keypoint_ids'] = json.dumps(kpids)

                if updates:
                    set_parts = []
                    params = {'cid': cid}
                    if 'angle_id' in updates:
                        set_parts.append('angle_id = :aid')
                        params['aid'] = updates['angle_id']
                    if 'keypoint_ids' in updates:
                        set_parts.append('keypoint_ids = :kps')
                        params['kps'] = updates['keypoint_ids']

                    c.execute(text(f"UPDATE ad_combos SET {', '.join(set_parts)} WHERE combo_id = :cid"), params)
                    updated += 1
                    print(f"  {cid} -> ANG={aid or '-'} KPs={len(kpids)}")

            c.commit()

    except Exception as e:
        print(f"  ERROR: {e}")

db.close()
print(f'\nDone! Updated {updated} combos')
