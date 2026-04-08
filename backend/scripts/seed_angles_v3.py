"""Seed 78 angles (13 types x 6 branches) with angle + hook separation."""
import sys, io, json, uuid, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from anthropic import Anthropic
from app.database import SessionLocal, engine
from app.models.account import AdAccount
from app.models.ad_angle import ANGLE_TYPES
from app.models.keypoint import BranchKeypoint
from app.models.ad_combo import AdCombo
from app.models.ad_copy import AdCopy
from app.models.ad_material import AdMaterial
from app.models.campaign import Campaign
from sqlalchemy import text
from datetime import datetime, timezone

db = SessionLocal()
client = Anthropic()

# Clear
with engine.connect() as c:
    c.execute(text('UPDATE ad_combos SET angle_id = NULL'))
    c.execute(text('DELETE FROM ad_angles'))
    c.commit()
print("Cleared")

accounts = db.query(AdAccount).filter(AdAccount.is_active.is_(True)).all()
keypoints = db.query(BranchKeypoint).filter(BranchKeypoint.is_active.is_(True)).all()
bctx = {}
for a in accounts:
    kps = [k.title for k in keypoints if k.branch_id == a.id]
    bctx[a.account_name] = {'id': a.id, 'kps': kps}

types_str = "\n".join([f"{i+1}. {t}" for i, t in enumerate(ANGLE_TYPES)])

example = json.dumps({
    "branch": "MEANDER Saigon",
    "angle_type": "Measure the size of the claim",
    "target_audience": "Solo",
    "angle_explain": "Use big numbers to build instant credibility and scale for MEANDER Saigon.",
    "hook_examples": [
        "42 rooms. 500+ reviews. 8.8 on Booking.com. This is MEANDER Saigon.",
        "125 guests a night choose this over a hotel. Here's why.",
        "Over 10,000 travelers have stayed here. Most wish they'd found it sooner."
    ]
}, ensure_ascii=False)

branches_str = json.dumps({k: v['kps'] for k, v in bctx.items()}, ensure_ascii=False, indent=1)

prompt = (
    "Create Ad Angles for MEANDER Group hotels. Always write MEANDER in uppercase.\n\n"
    "Angle = Strategic Approach (the big idea behind why someone should care)\n"
    "Hook = Opening Line (the specific sentence that stops the scroll)\n\n"
    f"13 ANGLE TYPES:\n{types_str}\n\n"
    f"BRANCHES:\n{branches_str}\n\n"
    "For EACH of the 6 branches, create ALL 13 angles. Total = 78.\n\n"
    "Each angle must have:\n"
    "- branch: exact name (MEANDER uppercase)\n"
    "- angle_type: exact type from list above\n"
    "- target_audience: Solo, Couple, or Group (vary across angles)\n"
    "- angle_explain: 1 sentence explaining the strategic approach for this branch\n"
    "- hook_examples: array of 3 specific scroll-stopping opening lines\n\n"
    f"EXAMPLE:\n{example}\n\n"
    "Return ONLY JSON array. No markdown."
)

print("Calling Claude (78 angles)...")
resp = client.messages.create(model="claude-sonnet-4-20250514", max_tokens=16000, messages=[{"role": "user", "content": prompt}])
raw = resp.content[0].text.strip()
if raw.startswith("```"):
    raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
angles = json.loads(raw)

now = datetime.now(timezone.utc).isoformat()
n = 1
with engine.connect() as c:
    for a in angles:
        bid = None
        for nm, info in bctx.items():
            bn = a['branch'].lower().replace('meander', '').strip()
            nn = nm.lower().replace('meander', '').strip()
            if bn in nn or nn in bn:
                bid = info['id']
                break
        aid = f"ANG-{n:03d}"
        n += 1
        hooks = json.dumps(a.get('hook_examples', []), ensure_ascii=False)
        c.execute(text(
            "INSERT INTO ad_angles (id, angle_id, branch_id, angle_type, angle_explain, hook_examples, "
            "target_audience, angle_text, hook, status, created_at, updated_at) "
            "VALUES (:id, :aid, :bid, :at, :ae, :he, :ta, :atxt, :hk, :st, :now, :now)"
        ), {
            'id': str(uuid.uuid4()), 'aid': aid, 'bid': bid,
            'at': a['angle_type'], 'ae': a['angle_explain'],
            'he': hooks, 'ta': a['target_audience'],
            'atxt': a['angle_explain'], 'hk': a['angle_type'],
            'st': 'TEST', 'now': now,
        })
    c.commit()
print(f"{len(angles)} angles created")

# Reassign combos
with engine.connect() as c:
    ar = c.execute(text("SELECT angle_id, branch_id, angle_type, target_audience FROM ad_angles")).fetchall()
al = [{'angle_id': r[0], 'branch_id': r[1], 'type': r[2], 'ta': r[3]} for r in ar]
ci = [{'combo_id': x.combo_id, 'ad_name': x.ad_name, 'branch_id': x.branch_id, 'ta': x.target_audience} for x in db.query(AdCombo).all()]

for i in range(0, len(ci), 25):
    batch = ci[i:i+25]
    r2 = client.messages.create(
        model="claude-sonnet-4-20250514", max_tokens=2000,
        messages=[{"role": "user", "content": f"Assign best angle_id to each combo by branch+theme. ANGLES:{json.dumps(al)} COMBOS:{json.dumps(batch)} Return JSON:[{{\"combo_id\":\"CMB-001\",\"angle_id\":\"ANG-001\"}}] Only JSON."}]
    )
    t2 = r2.content[0].text.strip()
    if t2.startswith("```"):
        t2 = t2.split("\n", 1)[1].rsplit("```", 1)[0]
    with engine.connect() as c:
        for x in json.loads(t2):
            c.execute(text("UPDATE ad_combos SET angle_id = :a WHERE combo_id = :c"), {'a': x.get('angle_id'), 'c': x['combo_id']})
        c.commit()
    print(f"Batch {i//25+1}")

db.close()
print("Done")
