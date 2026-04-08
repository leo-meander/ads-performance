"""Seed Creative Library data from 2026 campaigns + branch keypoints."""
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.database import SessionLocal
from app.models.account import AdAccount
from app.models.keypoint import BranchKeypoint
from app.models.ad_angle import AdAngle
from app.models.ad_copy import AdCopy
from app.models.ad_material import AdMaterial
from app.services.creative_service import next_angle_id, next_copy_id, next_material_id

db = SessionLocal()

# ── Account map ──
accs = {a.account_name: a for a in db.query(AdAccount).all()}
def acc_id(name_part):
    for k, v in accs.items():
        if name_part.lower() in k.lower():
            return v.id
    return None

# ── Clear existing seed data ──
db.query(BranchKeypoint).delete()
db.query(AdAngle).delete()
db.query(AdCopy).delete()
db.query(AdMaterial).delete()
db.commit()

# ══════════════════════════════════════════════════════════
# 1. KEYPOINTS (no description)
# ══════════════════════════════════════════════════════════
keypoints = [
    # Meander Saigon
    ("Saigon", "location", "Heart of District 1, HCMC"),
    ("Saigon", "location", "Walking distance to Ben Thanh Market & Bui Vien"),
    ("Saigon", "amenity", "Rooftop bar with city skyline view"),
    ("Saigon", "amenity", "Free breakfast buffet"),
    ("Saigon", "experience", "Local street food tour partnership"),
    ("Saigon", "value", "Best value boutique hotel in D1"),
    # Oani (Taipei)
    ("Oani", "location", "Zhongshan District — premium area"),
    ("Oani", "location", "5 min walk to MRT Zhongshan station"),
    ("Oani", "amenity", "Japanese-inspired minimalist design"),
    ("Oani", "amenity", "Premium bedding & amenities"),
    ("Oani", "experience", "Curated Taipei city guide for guests"),
    ("Oani", "value", "Boutique luxury at hostel-friendly price"),
    # Meander Osaka
    ("Osaka", "location", "Namba area — nightlife & shopping hub"),
    ("Osaka", "location", "2 min walk to Dotonbori"),
    ("Osaka", "amenity", "Japanese-style common area"),
    ("Osaka", "amenity", "Free luggage storage"),
    ("Osaka", "experience", "Cherry blossom season special packages"),
    ("Osaka", "experience", "Osaka food culture immersion"),
    ("Osaka", "value", "Affordable base for Kansai exploration"),
    # Meander Taipei
    ("Taipei", "location", "Ximending — youth & shopping district"),
    ("Taipei", "location", "Near Taipei Main Station"),
    ("Taipei", "amenity", "Modern co-working lounge"),
    ("Taipei", "experience", "Night market walking tour"),
    ("Taipei", "value", "Budget-friendly for solo backpackers"),
    # Meander 1948
    ("1948", "location", "Historic Dadaocheng area, Taipei"),
    ("1948", "location", "Near Dihua Street heritage market"),
    ("1948", "amenity", "Heritage building with modern renovation"),
    ("1948", "experience", "Cultural immersion in old Taipei"),
    ("1948", "value", "Unique heritage stay at budget price"),
]

for branch_part, cat, title in keypoints:
    bid = acc_id(branch_part)
    if bid:
        db.add(BranchKeypoint(branch_id=bid, category=cat, title=title))
db.commit()
print(f"Seeded {len(keypoints)} keypoints")

# ══════════════════════════════════════════════════════════
# 2. AD ANGLES (from campaign naming patterns)
# ══════════════════════════════════════════════════════════
angles_data = [
    # Solo angles
    (None, "Solo", "Budget-friendly solo adventure in vibrant city center", "WIN", "High ROAS across PH/SG markets"),
    (None, "Solo", "Solo traveler's perfect base — explore freely", "WIN", "Strong CTR for landing pages"),
    (None, "Solo", "Meet fellow travelers at our social hostel", "TEST", "New angle testing"),
    ("Saigon", "Solo", "Saigon street food & nightlife — solo explorer's paradise", "WIN", "Top performer SGN"),
    ("Osaka", "Solo", "Solo in Osaka — Dotonbori at your doorstep", "TEST", "Testing JP market"),
    ("Oani", "Solo", "Premium solo stay in Taipei's best district", "WIN", "Oani top ROAS angle"),
    ("Taipei", "Solo", "Taipei solo adventure from Ximending", "TEST", "Multiple markets tested"),
    ("1948", "Solo", "Heritage solo experience in old Taipei", "TEST", "1948 unique positioning"),
    # Couple angles
    ("Osaka", "Couple", "Romantic Osaka getaway — cherry blossom special", "WIN", "Sakura season high conversion"),
    ("Osaka", "Couple", "Couple's guide to Osaka food scene", "TEST", "Food angle testing"),
    ("Oani", "Couple", "Intimate boutique stay for two in Taipei", "TEST", "Premium couple positioning"),
    (None, "Couple", "Couple getaway — explore together, stay comfortably", "TEST", "Generic couple angle"),
    # Friend/Group angles
    ("Oani", "Group", "Friends trip to Taipei — group-friendly rooms", "WIN", "HK/CN Friend campaigns perform well"),
    (None, "Group", "Group travel made easy — shared spaces, shared memories", "TEST", "New group angle"),
    # Remarketing
    (None, "Solo", "Come back — exclusive returning guest discount", "TEST", "MOF remarketing angle"),
    # Engagement
    (None, "Solo", "Follow us for travel tips & hidden gems", "LOSE", "Low conversion from engagement"),
]

for branch_part, ta, text, status, notes in angles_data:
    bid = acc_id(branch_part) if branch_part else None
    aid = next_angle_id(db)
    db.add(AdAngle(angle_id=aid, branch_id=bid, target_audience=ta, angle_text=text, status=status, notes=notes))
    db.flush()
db.commit()
print(f"Seeded {len(angles_data)} angles")

# ══════════════════════════════════════════════════════════
# 3. AD COPIES (from campaign types)
# ══════════════════════════════════════════════════════════
copies_data = [
    # Saigon Solo
    ("Saigon", "Solo", "Explore Saigon Like a Local", "Your perfect solo base in District 1. Walk to Ben Thanh Market, explore Bui Vien street, and enjoy rooftop views. Book direct for best rates.", "Book Now", "en"),
    ("Saigon", "Solo", "Solo Adventure Awaits in HCMC", "Street food, nightlife, culture — all at your doorstep. Start your Saigon journey from the heart of the city.", "Explore & Book", "en"),
    # Oani Solo
    ("Oani", "Solo", "Premium Solo Stay in Taipei", "Japanese-inspired design meets Taipei convenience. 5 min to MRT, curated city guide included. Your boutique escape.", "Reserve Now", "en"),
    ("Oani", "Solo", "台北獨旅首選 — Oani精品旅宿", "中山區日式設計旅宿，步行5分鐘到捷運站。含精選台北旅遊指南。", "立即預訂", "zh"),
    # Oani Friend/Group
    ("Oani", "Group", "Friends Trip to Taipei? We've Got You", "Group-friendly rooms in Taipei's best district. Easy MRT access, premium amenities, unforgettable memories.", "Book for Your Group", "en"),
    ("Oani", "Group", "和好友一起來台北", "中山區團體友善住宿，交通便利，設施齊全。一起創造美好回憶。", "立即預訂", "zh"),
    # Osaka Couple
    ("Osaka", "Couple", "Romantic Osaka Getaway", "Walk to Dotonbori hand-in-hand. Cherry blossom views, Japanese hospitality, and Osaka's best food scene — all from your couple's retreat.", "Book Your Stay", "en"),
    ("Osaka", "Couple", "Cherry Blossom Couple Escape", "Sakura season in Osaka — limited availability. Premium couple rooms with city views and authentic Japanese experience.", "Reserve Sakura Special", "en"),
    # Osaka Generic
    ("Osaka", "Solo", "Your Osaka Base — Namba Location", "2 minutes to Dotonbori. Explore Kansai from the heart of Osaka. Free luggage storage, social common area.", "Book Direct", "en"),
    # Taipei Solo
    ("Taipei", "Solo", "Solo in Taipei — Start from Ximending", "Night markets, MRT access, modern co-working space. The perfect solo backpacker base in Taipei.", "Book Now", "en"),
    ("Taipei", "Solo", "Taipei Solo Backpacker's Dream", "Budget-friendly, perfectly located, socially designed. Meet fellow travelers while exploring Taipei your way.", "Check Availability", "en"),
    # 1948 Solo
    ("1948", "Solo", "Heritage Stay in Old Taipei", "Experience Dadaocheng's historic charm. Walk Dihua Street, discover heritage markets, stay in a beautifully renovated 1948 building.", "Discover 1948", "en"),
    ("1948", "Solo", "Taipei's Most Unique Stay", "Not just a hostel — a cultural experience. Heritage architecture meets modern comfort in historic Dadaocheng.", "Book Heritage Stay", "en"),
    # Remarketing
    ("Saigon", "Solo", "We Miss You — Come Back to Saigon", "Returning guest? Enjoy exclusive rates at Meander Saigon. Your favorite District 1 rooftop awaits.", "Claim Your Discount", "en"),
]

for branch_part, ta, headline, body, cta, lang in copies_data:
    bid = acc_id(branch_part)
    if bid:
        cid = next_copy_id(db)
        db.add(AdCopy(copy_id=cid, branch_id=bid, target_audience=ta, headline=headline, body_text=body, cta=cta, language=lang))
        db.flush()
db.commit()
print(f"Seeded {len(copies_data)} copies")

# ══════════════════════════════════════════════════════════
# 4. AD MATERIALS
# ══════════════════════════════════════════════════════════
materials_data = [
    # Saigon
    ("Saigon", "image", "Solo traveler on Saigon rooftop", "Solo", "https://drive.google.com/saigon-rooftop-solo"),
    ("Saigon", "video", "Saigon street food experience reel", "Solo", "https://drive.google.com/saigon-streetfood-reel"),
    ("Saigon", "carousel", "Saigon D1 highlights — 5 slides", "Solo", "https://drive.google.com/saigon-d1-carousel"),
    # Oani
    ("Oani", "image", "Oani minimalist room interior", "Solo", "https://drive.google.com/oani-room-minimal"),
    ("Oani", "image", "Oani common area lifestyle shot", "Group", "https://drive.google.com/oani-common-area"),
    ("Oani", "video", "Oani x Taipei city guide video", "Solo", "https://drive.google.com/oani-taipei-guide"),
    ("Oani", "carousel", "Oani facilities tour — 4 slides", None, "https://drive.google.com/oani-facilities"),
    # Osaka
    ("Osaka", "image", "Couple at Dotonbori night scene", "Couple", "https://drive.google.com/osaka-dotonbori-couple"),
    ("Osaka", "image", "Cherry blossom near Osaka Castle", "Couple", "https://drive.google.com/osaka-sakura"),
    ("Osaka", "video", "Osaka food scene 30s reel", "Solo", "https://drive.google.com/osaka-food-reel"),
    ("Osaka", "carousel", "Osaka neighborhood guide — 6 slides", None, "https://drive.google.com/osaka-neighborhood"),
    # Taipei
    ("Taipei", "image", "Solo backpacker at Ximending", "Solo", "https://drive.google.com/taipei-ximending-solo"),
    ("Taipei", "video", "Taipei night market adventure", "Solo", "https://drive.google.com/taipei-nightmarket"),
    ("Taipei", "carousel", "Taipei MRT travel guide", None, "https://drive.google.com/taipei-mrt-guide"),
    # 1948
    ("1948", "image", "1948 heritage building exterior", "Solo", "https://drive.google.com/1948-heritage-exterior"),
    ("1948", "image", "Dihua Street morning scene", "Solo", "https://drive.google.com/1948-dihua-morning"),
    ("1948", "video", "1948 heritage story — 45s film", None, "https://drive.google.com/1948-heritage-film"),
]

for branch_part, mtype, desc, ta, url in materials_data:
    bid = acc_id(branch_part)
    if bid:
        mid = next_material_id(db)
        db.add(AdMaterial(material_id=mid, branch_id=bid, material_type=mtype, file_url=url, description=desc, target_audience=ta))
        db.flush()
db.commit()
print(f"Seeded {len(materials_data)} materials")

db.close()
print("\nDone! Creative library seeded.")
