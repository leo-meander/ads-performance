# Creative Intelligence — Rationale & Design Decisions

> **Mục đích file này:** Ghi lại *tại sao* hệ thống được thiết kế theo cách đó,
> không phải *cái gì* được build (phần đó nằm trong System Spec + Operator Playbook).
> Đọc cái này trước khi sửa spec — mọi quyết định đều có lý do.

---

## Cụm 1 — Nền tảng chiến lược (Brand & Desire)

### Brand Intelligence
- 5 branch có nhân cách khác biệt rõ, NEVER SAY là phần dùng được nhất.
- **Giới hạn quan trọng:** Brand Intelligence là hiến pháp brand, không phải ad brief. Nó không phân theo tầng phễu → không được dùng để copy 1:1 khi viết ad.
- Lỗi cụ thể cần sửa sau: Taipei cấm "best location" (phí, nên cấm bằng chứng thay vì cụm từ), Saigon "never say visit" quá cực đoan với cold audience, Osaka "giấc mơ Nhật" chung chung, 1948 lặp "Shopping" hai lần.
- Oani là branch viết brand tốt nhất hiện tại.

### Human Desire
- Desire = động cơ gốc, khác nhu cầu (cái cần) và khác lý do nói ra (rationalization).
- **Chốt lớn:** Desire thắng ở khâu chú ý và click. Proof thắng ở khâu book. Không thể dùng desire suốt cả phễu.
- Khách sạn đặc biệt: mua bằng tưởng tượng + gắn bản sắc → desire nặng ký hơn hàng tiêu dùng thông thường.
- **Điều kiện để desire ăn:** đúng người (TA) + đúng tầng phễu + có proof đỡ lưng.

### Landing Page vs Ad Message
- Đọc 5 landing page → mỗi branch lộ ICP rõ hơn brand brief.
- **Phát hiện quan trọng (Oani):** Brand page nói *Stillness*, landing page bán *Effortlessness* → nguy cơ gãy message-match giữa ad và landing. Cần chốt một trước khi scale.
- Câu hỏi "desire kéo khách vào landing có đúng không" → đúng hướng sai chủ từ: ad kéo, không phải desire kéo. Desire là điểm khởi đầu, không phải cả phễu.

---

## Cụm 2 — Chẩn đoán & Sửa Creative Intelligence

### 4 lỗi gốc của dashboard cũ
1. **Angle vừa thắng vừa thua** → đo sai tầng, không phải angle kém.
2. **"Validated = ROAS" sai.** Ví dụ cụ thể: HYP-270 (CTR 14%, 9 booking) là con leak — click nhiều nhưng không đóng đơn. HYP-247 mới là con đóng đơn giỏi hơn ~12 lần. Dùng ROAS để validate creative hypothesis là nhầm tầng.
3. **"Top Desire 37%"** là tần suất test (team hay chọn desire đó để test), không phải win rate (desire đó có thắng không).
4. **Chia chiều quá mỏng** → mỗi ô quá ít data, kết luận không có ý nghĩa thống kê.

### 3 fix đã implement
- **Tách verdict:** Layer A (creative: hook/hold/CTR) độc lập với Layer B (downstream: ROAS/booking). Không bao giờ override nhau.
- **Win rate + min-sample gate:** Dashboard chỉ show win rate khi đủ min_sample (default 5 concluded ads). Dưới ngưỡng → greyed out, không kết luận.
- **Gom chiều:** Mỗi quý chỉ học một trục biến, không dàn trải.

### Dashboard nguyên tắc đọc
Đọc theo thứ tự: **branch → desire → angle → stage**. Không đào sâu vào angle khi chưa biết desire nào đang work ở branch đó.

---

## Cụm 3 — Đo lường (phần kỹ thuật nhất)

### Tại sao không chia theo format mà chia theo funnel stage
- Đề xuất ban đầu: ảnh đo CTR + Engagement, video đo CTR + hook + ThruPlay.
- **Sửa lại:** Quan trọng hơn là chia theo *khâu phễu* (Stop / Hold / Click), vì cùng một video có thể giỏi Stop nhưng kém Hold. Format chỉ xác định metric nào đo được, không phải metric nào quan trọng.

### Nguyên tắc "mỗi hypothesis một chỉ số"
- Primary metric phải *cùng khâu* với điều hypothesis khẳng định. Hook test → đo hook_rate. CTA test → đo CTR.
- Secondary metric chỉ để đọc thêm, không dùng để phán verdict.

### Funnel stage → Primary metric mapping
| Stage | Video | Image |
|---|---|---|
| Stop | hook_rate (3s views ÷ impressions) | thumb_stop_rate → thực ra = hook_rate, nhưng ảnh không có video 3s → **ảnh chấm bằng CTR** |
| Hold | hold_rate (thruplay ÷ impressions) | hold_rate (không có → dùng CTR) |
| Click | CTR | CTR |
| Downstream | booking_rate (Layer B) | booking_rate (Layer B) |

- **Chú ý:** thumb_stop_rate ban đầu trong spec = hook_rate (3s views ÷ impressions), chỉ có ý nghĩa với video. Ảnh không có chỉ số này → ảnh Stop = CTR. Đây là chỗ spec tự sửa lại so với phiên bản đầu.

### Downstream = Layer B, tách riêng
Downstream là khâu sau khi bấm vào landing: book hay không. Nó bị ảnh hưởng bởi landing page, giá, mùa → không phải lỗi của creative → không được dùng để phán Layer A.

---

## Cụm 4 — Tranh luận Behavior vs Execution

### Điều đồng ý
Behavior hypothesis (vd: "khách muốn cảm thấy được hiểu, không muốn bị pitch") sống lâu hơn execution (vd: "dùng font X, ảnh Y"). Nâng behavior lên làm đơn vị tri thức là đúng hướng — nó generate được nhiều execution, có thể tái dùng qua nhiều quý.

### Điều không đồng ý — tại sao không bỏ execution
- Execution là thứ duy nhất có số đo được (hook_rate, CTR...).
- Bỏ execution → behavior lơ lửng, không neo vào data → confounding bias quay lại → mất chỗ cắm funnel_stage.

### Kết luận tranh luận
- Execution *đã có nhà*: Angle + Keypoint + Format + combo_id. Không cần field riêng trong hypothesis.
- Nhưng cần **dây nối behavior ↔ execution**: combo_id trong hypothesis chính là dây đó.
- Roll-up verdict cần ở cả hai tầng: Layer A (execution verdict) và behavior pattern (tổng hợp từ nhiều Layer A cùng behavior).

---

## Cụm 5 — Kế hoạch đào data thật

### Tình trạng schema
- Execution link tốt qua `combo_id` trong `creative_hypotheses`.
- Behavior chưa có thực thể để tích lũy — ở quy mô 27 experiment thì **đừng xây bảng behavior**, chỉ chừa móc `behavior_id` để sau này link được.

### 232 combo — cơ hội retroactive mining
- 232 combo là số lớn hơn dự kiến → đào ngược (retroactive mining) khả thi về mặt kỹ thuật.
- **Cảnh báo:** 232 combo ≠ 232 experiment học được. Đây là correlation từ data đã chạy, không phải controlled experiment. Phải test lại sạch mới thành kết luận.

### Bẫy khi link tay
Hai lỗi cần tránh:
1. **Survivorship bias:** chọn winner để link → mất mẫu số loser → win rate ảo.
2. **Chết đuối vì link tay:** 232 combo × nhiều field = không thể làm tay đủ.

**Đổi hướng:** Nhóm theo *trục biến* trước (vd: text_density cao vs thấp), tìm cặp tương phản, không tìm "ad tốt". Đây là cách biến correlation thành thứ gần với experiment hơn.

### 3 vấn đề trong Creative Library hiện tại
1. Cột Verdict chấm bằng ROAS → mâu thuẫn với Layer A/B split vừa xây.
2. Image 0.04x ROAS = data hỏng (tracking issue hoặc wrong attribution), không phải creative kém.
3. Booking phần lớn = 0 → không đào được bằng conversion. Phải đào bằng Hook rate + CTR, luôn kèm Country filter để vá confounding.

### Schema đào data
- `creative_visual_tags` là chìa khoá: `text_density`, `human_presence`, `hook_type` chính là các trục biến. Biến việc đào tay thành một câu `GROUP BY`.
- `ad_country_metrics` vá confounding theo country.
- Behavior layer ở giai đoạn này = quan hệ `(tag × stage × metric × country)`, gần như không cần bảng nặng thêm.

### Nước đi đầu tiên
```sql
SELECT
  cvt.tag_value AS text_density,
  AVG(ac.hook_rate) AS avg_hook_rate,
  AVG(ac.ctr) AS avg_ctr,
  COUNT(*) AS sample
FROM ad_combos ac
JOIN creative_visual_tags cvt ON cvt.material_id = ac.material_id
WHERE cvt.tag_category = 'text_density'
  AND ac.branch_id = '<branch>'
GROUP BY cvt.tag_value
ORDER BY avg_hook_rate DESC;
```
→ So hook_rate + CTR trong cùng branch+country theo text_density. Đây là hypothesis đầu tiên có thể test sạch.

---

## Open Questions (chưa trả lời — quyết định bước tiếp theo)

1. **visual_tags phủ bao nhiêu trong 232 combo?**
   Nếu < 30% có tag → đào không có ý nghĩa, cần chạy vision tagging trước.
   → Kiểm tra: `SELECT COUNT(DISTINCT material_id) FROM creative_visual_tags` so với tổng material.

2. **Một ad_combo join xuống ad_daily_metrics có sạch grain không?**
   Một combo có thể trải qua nhiều ad_id × adset_id × country → aggregation sẽ inflate nếu không group đúng.
   → Cần verify: mỗi combo_id map sang bao nhiêu platform_ad_id distinct.

**Hai câu này quyết định có bắt đầu đào retroactive được chưa.**
