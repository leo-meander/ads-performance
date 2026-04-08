"""Use Claude AI to analyze combos and auto-assign keypoints + angles."""
import sys, io, os, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from anthropic import Anthropic

from app.config import settings
from app.database import SessionLocal
from app.models.account import AdAccount
from app.models.ad_angle import AdAngle
from app.models.ad_combo import AdCombo
from app.models.ad_copy import AdCopy
from app.models.ad_material import AdMaterial
from app.models.campaign import Campaign
from app.models.keypoint import BranchKeypoint

db = SessionLocal()
client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

# Load all keypoints and angles
keypoints = db.query(BranchKeypoint).filter(BranchKeypoint.is_active.is_(True)).all()
angles = db.query(AdAngle).all()
accounts = {a.id: a.account_name for a in db.query(AdAccount).all()}

# Format keypoints for AI
kp_list = []
for kp in keypoints:
    branch = accounts.get(kp.branch_id, '?')
    kp_list.append({"id": kp.id, "branch": branch, "category": kp.category, "title": kp.title})

ang_list = []
for a in angles:
    branch = accounts.get(a.branch_id, 'All') if a.branch_id else 'All'
    ang_list.append({"angle_id": a.angle_id, "branch": branch, "ta": a.target_audience, "text": a.angle_text, "status": a.status})

# Load combos with their copy text
combos = db.query(AdCombo).all()
copies = {c.copy_id: c for c in db.query(AdCopy).all()}

# Build combo info for AI
combo_infos = []
for combo in combos:
    copy = copies.get(combo.copy_id)
    branch = accounts.get(combo.branch_id, '?')
    combo_infos.append({
        "combo_id": combo.combo_id,
        "ad_name": combo.ad_name,
        "branch": branch,
        "headline": copy.headline[:100] if copy else "",
        "body_preview": copy.body_text[:150] if copy else "",
        "ta": copy.target_audience if copy else "Solo",
    })

# Process in batches of 15
BATCH_SIZE = 15
updated = 0

for i in range(0, len(combo_infos), BATCH_SIZE):
    batch = combo_infos[i:i+BATCH_SIZE]
    print(f"\nBatch {i//BATCH_SIZE + 1}: combos {batch[0]['combo_id']} - {batch[-1]['combo_id']}")

    prompt = f"""You are analyzing hotel ad combos for MEANDER Group. For each combo, assign:
1. The BEST matching keypoint_id (from the keypoints list) — match by branch + relevance to ad content
2. The BEST matching angle_id (from the angles list) — match by branch + target audience + theme

KEYPOINTS:
{json.dumps(kp_list, ensure_ascii=False, indent=1)}

ANGLES:
{json.dumps(ang_list, ensure_ascii=False, indent=1)}

COMBOS TO ASSIGN:
{json.dumps(batch, ensure_ascii=False, indent=1)}

Return ONLY a JSON array with objects like:
[{{"combo_id": "CMB-001", "keypoint_id": "uuid-here", "angle_id": "ANG-001"}}]

Rules:
- keypoint MUST belong to the same branch as the combo
- angle should match the target audience and theme (prefer same branch, but "All" branch angles are ok)
- If no good match exists, use null
- Return valid JSON only, no markdown, no explanation."""

    try:
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        # Clean up potential markdown
        if text.startswith('```'):
            text = text.split('\n', 1)[1]
            text = text.rsplit('```', 1)[0]

        assignments = json.loads(text)

        for asgn in assignments:
            combo_id = asgn.get("combo_id")
            kp_id = asgn.get("keypoint_id")
            ang_id = asgn.get("angle_id")

            combo = db.query(AdCombo).filter(AdCombo.combo_id == combo_id).first()
            if combo:
                if kp_id:
                    combo.keypoint_id = kp_id
                if ang_id:
                    combo.angle_id = ang_id
                updated += 1
                print(f"  {combo_id} -> KP={kp_id[:8] if kp_id else 'null'}... ANG={ang_id or 'null'}")

        db.commit()

    except Exception as e:
        print(f"  ERROR: {e}")

db.close()
print(f"\nDONE! Updated {updated} combos with keypoints + angles")
