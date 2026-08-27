/**
 * GROWTH TEAM — [MEANDER GROUP] CAMPAIGN REPORT
 * =============================================
 * Tự điền 3 bảng META / GOOGLE / TIKTOK theo tháng cho 2 tab:
 *   • "Total Budget_Paid Ads"  — cả group, VND, KHÔNG có Bread (BE&)
 *   • "BE& Only_Paid Ads"      — chỉ Bread, để tiền gốc NT$ (TWD)
 * Data kéo từ Ads Platform:
 *   GET /api/export/kpi/paid-ads-monthly?year=YYYY&platform=meta|google|tiktok
 * Endpoint này mirror đúng số của dashboard (/dashboard/country):
 *   - chỉ metrics_cache CAMPAIGN-level (không double-count adset/ad)
 *   - chỉ country hợp lệ (ISO-2 hoặc 'ALL')
 *   - có sẵn cả spend_native lẫn spend_vnd → mỗi tab lấy loại tiền của nó
 * 1 lần chạy = 3 call API (mỗi platform 1 call), dùng chung cho cả 2 tab.
 *
 * GHI GÌ / KHÔNG GHI GÌ:
 *   ✍️  Spent (-VAT)      ← spend (VND hoặc native tuỳ tab)
 *   ✍️  Booking/Purchase  ← conversions
 *   ✍️  Revenue           ← revenue
 *   ✍️  ROAS              ← công thức =Revenue/Spent (để nó tự sống)
 *   ✍️  Leads         ← leads (Meta lead actions / Google SUBMIT_LEAD_FORM),
 *       chỉ ghi khi API > 0 nên số nhập tay không bị 0 đè lên.
 *   ✍️  Cost per lead ← công thức Spent/Leads (ô gõ tay sẵn thì không đụng)
 *   ✋  Bảng TOTAL CHANNEL ← KHÔNG ghi số (nó sống bằng công thức của sheet),
 *       chỉ KÉO công thức từ cột tháng trước sang cột tháng mới còn trống —
 *       nếu không, tháng mới chèn sẽ trống trơn vì không có công thức nào.
 *   ✋  Cột "Total"    ← không ghi đè, chỉ NỚI range của =SUM(C4:O4) thành
 *       =SUM(C4:P4) cho ôm cột mới. Công thức khác (ROAS tổng =Q8/Q4…) để yên.
 *
 * CỘT THÁNG:
 *   Script đọc dòng header của từng bảng ("Jan - 2026", "Jul (1st-27th)"…) để
 *   biết tháng nào nằm cột nào. Bảng nào thiếu nhãn thì script tự điền vào,
 *   bắt chước kiểu chữ của chính bảng đó ("June - 2026" → "July - 2026",
 *   "Jul (1st-27th)" → "Aug"). Nếu CẢ 3 bảng của tab đó đều chưa có cột cho
 *   tháng cần ghi và AUTO_ADD_COLUMN = true → chèn cột mới ngay sau cột tháng
 *   cuối cùng, rồi kéo công thức + nới SUM như trên.
 *
 * CÁCH DÙNG:
 *   1. Sheet → Extensions → Apps Script → dán file này → Save.
 *   2. Sửa CONFIG: ADS_BASE_URL, ADS_API_KEY (admin tạo: POST /api/export/keys).
 *   3. Reload sheet → menu "Ads Sync" hiện ra.
 *   4. "Xem thử (dry run)" trước cho chắc → rồi "Cập nhật tháng gần nhất".
 *   5. (Tuỳ chọn) "Đặt lịch tự chạy mỗi sáng".
 */

// ============================ CONFIG ============================
var CONFIG = {
  ADS_BASE_URL: 'https://ads-performance-fuls.zeabur.app',  // KHÔNG có / ở cuối
  ADS_API_KEY:  'REPLACE-WITH-X-API-KEY',

  YEAR: 0,                  // 0 = năm hiện tại. Set 2026 nếu muốn ép cứng.

  // Mỗi tab = 1 target. Muốn tạm tắt tab nào thì set enabled: false.
  TARGETS: [
    {
      name: 'Tab tổng',
      sheetName: 'Total Budget_Paid Ads',
      enabled: true,
      onlyBranches: [],          // [] = lấy hết, trừ excludeBranches
      excludeBranches: ['Bread'],// BE& có tab riêng → không tính vào tab tổng
      currency: 'VND',           // dùng spend_vnd / revenue_vnd
      startYear: null,           // null = không giới hạn mốc bắt đầu
      startMonth: null,
    },
    {
      name: 'Tab BE&',
      sheetName: 'BE& Only_Paid Ads',
      enabled: true,
      onlyBranches: ['Bread'],   // chỉ Bread Espresso
      excludeBranches: [],
      currency: 'NATIVE',        // tab này để NT$ → dùng spend_native
      // BE& mở sau nên khung thời gian KHÁC các branch kia: bảng chỉ tính từ
      // 05/2026. Không có mốc này thì "Cập nhật cả năm" sẽ đòi thêm cột
      // Jan–Apr cho tab này rồi nhét vào đuôi → loạn thứ tự tháng.
      startYear: 2026,
      startMonth: 5,
    },
  ],

  // 'recent' = chỉ tháng này + tháng trước (an toàn, không đụng số cũ nhập tay)
  // 'all'    = ghi đè từ SYNC_FROM_MONTH đến tháng hiện tại
  OVERWRITE: 'recent',
  SYNC_FROM_MONTH: 1,       // chỉ dùng khi OVERWRITE = 'all'

  VAT_RATE: 0,              // 0 = spend từ API coi như đã ex-VAT. Set 0.05 nếu
                            // muốn script tự bóc 5% VAT ra: spend / (1 + rate).

  SKIP_EMPTY_MONTH: true,   // tháng API trả spend=0 & revenue=0 → bỏ qua, không
                            // ghi 0 đè lên số đang có (phòng khi sync đang hỏng).

  WRITE_LEADS: true,        // điền dòng Leads từ API (Meta lead actions /
                            // Google SUBMIT_LEAD_FORM). Chỉ ghi khi API > 0 —
                            // không bao giờ ghi 0 đè lên số nhập tay.
  WRITE_ROAS_FORMULA: true, // ROAS ghi công thức thay vì số cứng
  WRITE_COST_PER_LEAD: true,// đặt công thức Cost per lead = Spent / Leads
  BUILD_TOTAL_FORMULA: true,// bảng TOTAL CHANNEL: ô trống mà không có công thức
                            // tháng trước để kéo → tự dựng =Meta+Google+TikTok
  AUTO_ADD_COLUMN: true,    // chèn cột khi cả 3 bảng đều chưa có tháng đó
  COPY_FORMULA_COLUMN: true,// cột tháng mới: kéo công thức từ cột tháng trước
                            // sang (bảng TOTAL CHANNEL + mọi ô đang trống).
  EXTEND_TOTAL_SUM: true,   // nới =SUM(C4:O4) ở cột Total để ôm cột mới
  UPDATE_PARTIAL_LABEL: true, // cập nhật nhãn "(1st-27th)" theo ngày có data cuối
  FINALIZE_PAST_LABELS: true, // tháng đã đủ data cả tháng → gỡ đuôi "(1st-27th)"

  MAX_SCAN_ROW: 80,         // quét tối đa bao nhiêu dòng để tìm các bảng
  MAX_SCAN_COL: 40,         // quét tối đa bao nhiêu cột trên dòng header
  FIRST_MONTH_COL: 3,       // cột C — cột đầu tiên có thể chứa tháng
};
// ===============================================================

var PLATFORMS = [
  { key: 'meta',   match: 'META' },
  { key: 'google', match: 'GOOGLE' },
  { key: 'tiktok', match: 'TIKTOK' },
];

var MONTH_ABBR = ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'];
var MONTH_FULL = ['January','February','March','April','May','June',
                  'July','August','September','October','November','December'];


function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Ads Sync')
    .addItem('Cập nhật tháng gần nhất (cả 2 tab)', 'syncRecentMonths')
    .addItem('Cập nhật cả năm (cả 2 tab)', 'syncWholeYear')
    .addSeparator()
    .addItem('Chỉ tab tổng', 'syncMainOnly')
    .addItem('Chỉ tab BE&', 'syncBeOnly')
    .addSeparator()
    .addItem('Xem thử (dry run)', 'syncDryRun')
    .addItem('Debug: vì sao tháng này không ra số?', 'debugCheck')
    .addSeparator()
    .addItem('Đặt lịch tự chạy mỗi sáng', 'installDailyTrigger')
    .addItem('Xoá lịch tự chạy', 'removeDailyTrigger')
    .addToUi();
}

function syncRecentMonths() { runAll_({ mode: 'recent', dryRun: false }); }
function syncWholeYear()    { runAll_({ mode: 'all',    dryRun: false }); }
function syncDryRun()       { runAll_({ mode: CONFIG.OVERWRITE, dryRun: true }); }
function syncMainOnly()     { runAll_({ mode: CONFIG.OVERWRITE, dryRun: false, only: 0 }); }
function syncBeOnly()       { runAll_({ mode: CONFIG.OVERWRITE, dryRun: false, only: 1 }); }
/** Dùng cho trigger theo lịch — luôn chạy theo CONFIG.OVERWRITE, cả 2 tab. */
function syncCampaignReport() { runAll_({ mode: CONFIG.OVERWRITE, dryRun: false }); }


// ========================= LÕI =========================

/** Chạy lần lượt từng target. 1 tab lỗi không được kéo tab kia chết theo. */
function runAll_(opts) {
  var targets = CONFIG.TARGETS.filter(function (t, i) {
    if (opts.only !== undefined && opts.only !== i) return false;
    return t.enabled !== false;
  });
  if (!targets.length) { toast_('Không có target nào đang bật.'); return; }

  var report = [];
  var totalWritten = 0;
  targets.forEach(function (t) {
    try {
      var res = runSync_(t, opts);
      totalWritten += res.written;
      report.push('===== ' + t.name + ' (' + t.sheetName + ') =====');
      report.push(res.text);
    } catch (e) {
      report.push('===== ' + t.name + ' (' + t.sheetName + ') =====');
      report.push('❌ LỖI: ' + e);
    }
    report.push('');
  });

  var body = report.join('\n');
  Logger.log(body);
  if (opts.dryRun) alertLong_('Ads Sync — xem thử', body);
  else toast_('Đã cập nhật ' + totalWritten + ' ô-tháng. Chi tiết ở Executions log.');
}


/** Đổ data vào 1 tab. Trả { written, text }. */
function runSync_(target, opts) {
  var sheet = SpreadsheetApp.getActive().getSheetByName(target.sheetName);
  if (!sheet) throw new Error('Không thấy tab "' + target.sheetName + '".');

  var now = new Date();
  var year = CONFIG.YEAR || now.getFullYear();
  var curMonth = (year === now.getFullYear()) ? now.getMonth() + 1 : 12;
  var months = monthsToWrite_(opts.mode, curMonth).filter(function (m) {
    return afterStart_(target, year, m);
  });
  if (!months.length) {
    return { written: 0, text: 'Không tháng nào nằm trong khung thời gian của tab này.' };
  }

  var blocks = findBlocks_(sheet);
  if (blocks.length === 0) {
    throw new Error('Không tìm thấy bảng META/GOOGLE/TIKTOK nào (dòng có cột B = "Metrics").');
  }

  // Map tháng → cột, gộp header của CẢ 3 bảng (3 bảng dùng chung cột).
  var monthCol = buildMonthColumnMap_(sheet, blocks, year);

  // Thiếu cột hoàn toàn → chèn mới (nếu được phép).
  var added = [];
  var skippedOld = [];
  months.forEach(function (m) {
    if (monthCol[m]) return;
    if (!CONFIG.AUTO_ADD_COLUMN) return;
    // CHỈ nối cột về BÊN PHẢI, cho tháng mới hơn mọi cột đang có. Tháng cũ hơn
    // mà thiếu cột = bảng cố tình không theo dõi tháng đó (vd BE& chỉ chạy từ
    // 05/2026) → chèn vào là ra kiểu "Jan nằm sau Jul".
    if (m < maxMappedMonth_(monthCol)) { skippedOld.push(m); return; }
    if (!opts.dryRun) monthCol[m] = insertMonthColumn_(sheet, monthCol);
    added.push(m);
  });

  var log = [];
  var written = 0;

  blocks.forEach(function (block) {
    if (!block.platform) return;                // bảng TOTAL CHANNEL → xử sau
    var series = fetchPlatformMonths_(year, block.platform, target);

    months.forEach(function (m) {
      var col = monthCol[m];
      // Dry run không chèn cột thật, nhưng vẫn in số của tháng sắp được thêm.
      var pending = !col && opts.dryRun && CONFIG.AUTO_ADD_COLUMN;
      if (!col && !pending) { log.push(label_(block, m) + ': thiếu cột, bỏ qua'); return; }

      var d = series[m] || { spend: 0, revenue: 0, conversions: 0, leads: 0 };
      var spend = CONFIG.VAT_RATE > 0 ? d.spend / (1 + CONFIG.VAT_RATE) : d.spend;
      spend = Math.round(spend);
      var revenue = Math.round(d.revenue);

      if (CONFIG.SKIP_EMPTY_MONTH && spend === 0 && revenue === 0) {
        log.push(label_(block, m) + ': API trả 0 — bỏ qua');
        return;
      }

      log.push(label_(block, m) + ': spend ' + fmt_(spend) + ' | booking ' +
               d.conversions + ' | lead ' + d.leads + ' | revenue ' + fmt_(revenue) +
               ' | ROAS ' + (spend > 0 ? (revenue / spend).toFixed(2) : '-'));
      if (opts.dryRun) return;

      writeHeaderLabel_(sheet, block, m, col, monthCol, year, curMonth, block.platform, target);

      if (block.rows.spend)   sheet.getRange(block.rows.spend, col).setValue(spend);
      if (block.rows.booking) sheet.getRange(block.rows.booking, col).setValue(d.conversions);
      if (block.rows.revenue) sheet.getRange(block.rows.revenue, col).setValue(revenue);

      // Leads: chỉ ghi khi API có số > 0. Platform nào không chạy lead ads sẽ
      // trả 0 — ghi 0 vào là xoá mất số Mason nhập tay từ nguồn khác.
      if (CONFIG.WRITE_LEADS && block.rows.leads && d.leads > 0) {
        sheet.getRange(block.rows.leads, col).setValue(d.leads);
      }

      var a1 = colLetter_(sheet, col);

      if (block.rows.roas) {
        if (CONFIG.WRITE_ROAS_FORMULA && block.rows.spend && block.rows.revenue) {
          sheet.getRange(block.rows.roas, col).setFormula(
            '=IF(' + a1 + block.rows.spend + '=0,0,' + a1 + block.rows.revenue +
            '/' + a1 + block.rows.spend + ')');
        } else {
          sheet.getRange(block.rows.roas, col).setValue(spend > 0 ? revenue / spend : 0);
        }
      }

      // Cost per lead: luôn đặt công thức (ô trống hoặc đang là công thức) để
      // khi nào Leads có số là nó tự ra, khỏi phải quay lại điền tay.
      if (CONFIG.WRITE_COST_PER_LEAD) {
        setCostPerLead_(sheet, block, col, a1);
      }
      written++;
    });
  });

  // Bảng TOTAL CHANNEL chạy bằng công thức của sheet, script không ghi số vào.
  // Nhưng cột tháng MỚI chèn thì trống công thức → kéo từ cột tháng trước sang,
  // nếu không nhìn như bảng tổng "mất tiêu" tháng mới.
  if (!opts.dryRun && CONFIG.COPY_FORMULA_COLUMN) {
    months.forEach(function (m) {
      var col = monthCol[m];
      if (!col) return;
      blocks.forEach(function (block) {
        var n = copyFormulaColumn_(sheet, block, m, col, monthCol, year, curMonth, target);
        if (n) log.push((block.platform || 'TOTAL') + ' ' + MONTH_FULL[m - 1] +
                        ': kéo ' + n + ' công thức từ cột tháng trước');
        // Bảng TOTAL CHANNEL: ô nào vẫn trống (cột tháng trước là SỐ GÕ TAY chứ
        // không phải công thức nên chẳng có gì để kéo) → tự dựng công thức cộng
        // 3 bảng platform. Không bao giờ đè ô đã có nội dung.
        if (!block.platform && CONFIG.BUILD_TOTAL_FORMULA) {
          var k = buildTotalFormulas_(sheet, blocks, block, col);
          if (k) log.push('TOTAL ' + MONTH_FULL[m - 1] + ': dựng ' + k + ' công thức tổng');
        }
      });
    });
  }

  if (!opts.dryRun && CONFIG.EXTEND_TOTAL_SUM) {
    var extended = 0;
    blocks.forEach(function (block) { extended += extendTotalSum_(sheet, block, monthCol); });
    if (extended) log.push('Cột Total: nới ' + extended + ' công thức SUM cho ôm cột mới');
  }

  var head = (opts.dryRun ? '[DRY RUN] ' : '') + 'Năm ' + year +
             ' — tháng: ' + months.join(', ') +
             ' | branch: ' + branchScopeText_(target) +
             ' | tiền: ' + (target.currency === 'NATIVE' ? 'native' : 'VND');
  if (added.length) {
    head += '\n⚠️ ' + (opts.dryRun ? 'Sẽ thêm' : 'Đã thêm') + ' cột cho tháng: ' + added.join(', ');
  }
  if (skippedOld.length) {
    head += '\nℹ️ Bỏ qua tháng ' + skippedOld.join(', ') +
            ': cũ hơn cột sớm nhất của bảng này → không chèn, khỏi loạn thứ tự.';
  }
  return { written: written, text: head + '\n' + log.join('\n') };
}


/** Tháng lớn nhất đang có cột trong sheet (0 nếu chưa có cột nào). */
function maxMappedMonth_(monthCol) {
  var max = 0;
  for (var m in monthCol) if (Number(m) > max) max = Number(m);
  return max;
}

/** (year, month) có từ mốc startYear/startMonth của target trở đi không. */
function afterStart_(target, year, month) {
  if (!target.startYear && !target.startMonth) return true;
  var sy = target.startYear || year;
  var sm = target.startMonth || 1;
  return year > sy || (year === sy && month >= sm);
}

function monthsToWrite_(mode, curMonth) {
  var out = [];
  if (mode === 'all') {
    for (var m = CONFIG.SYNC_FROM_MONTH; m <= curMonth; m++) out.push(m);
  } else {
    if (curMonth > 1) out.push(curMonth - 1);
    out.push(curMonth);
  }
  return out;
}


// ==================== Dò cấu trúc sheet ====================

/**
 * Trả về mảng block:
 *   { platform, headerRow, rows: {spend, leads, cpl, booking, revenue, roas} }
 * Nhận diện: dòng có cột B = "Metrics" là dòng header; tiêu đề bảng nằm 1–3 dòng trên.
 */
function findBlocks_(sheet) {
  var lastRow = Math.min(sheet.getLastRow(), CONFIG.MAX_SCAN_ROW);
  var colA = sheet.getRange(1, 1, lastRow, 1).getValues();
  var colB = sheet.getRange(1, 2, lastRow, 1).getValues();
  var blocks = [];

  for (var i = 0; i < lastRow; i++) {
    if (norm_(colB[i][0]) !== 'metrics') continue;
    var headerRow = i + 1;

    // Tiêu đề: quét ngược tối đa 3 dòng, lấy chữ đầu tiên khớp platform.
    var platform = null;
    for (var back = 1; back <= 3 && headerRow - back >= 1; back++) {
      var titleRow = sheet.getRange(headerRow - back, 1, 1, Math.min(6, sheet.getMaxColumns())).getValues()[0];
      var joined = titleRow.map(function (v) { return String(v || ''); }).join(' ').toUpperCase();
      for (var p = 0; p < PLATFORMS.length; p++) {
        if (joined.indexOf(PLATFORMS[p].match) >= 0) { platform = PLATFORMS[p].key; break; }
      }
      if (platform) break;
      if (joined.indexOf('TOTAL') >= 0) break;  // bảng TOTAL CHANNEL — bỏ qua hẳn
    }

    // Các dòng metric ngay dưới header, dừng khi cả cột A lẫn B đều trống.
    var rows = {};
    for (var r = headerRow + 1; r <= lastRow; r++) {
      var lbl = norm_(colB[r - 1][0]);
      if (!lbl) {
        if (!norm_(colA[r - 1][0])) break;
        continue;
      }
      if (lbl === 'metrics') break;
      if (lbl.indexOf('cost per lead') >= 0)   rows.cpl = r;
      else if (lbl.indexOf('spent') >= 0)      rows.spend = r;
      else if (lbl.indexOf('lead') >= 0)       rows.leads = r;
      else if (lbl.indexOf('booking') >= 0 ||
               lbl.indexOf('purchase') >= 0)   rows.booking = r;
      else if (lbl.indexOf('revenue') >= 0)    rows.revenue = r;
      else if (lbl.indexOf('roas') >= 0)       rows.roas = r;
    }
    blocks.push({ platform: platform, headerRow: headerRow, rows: rows });
  }
  return blocks;
}


/**
 * Gộp header của mọi block → { monthNum: colIndex } cho đúng năm target.
 *
 * 2 lượt, và thứ tự này QUAN TRỌNG:
 *   Lượt 1 — chỉ nhãn ghi rõ năm ("August - 2026"). Đây là nguồn tin cậy.
 *   Lượt 2 — nhãn không ghi năm ("Jul (1st-27th)"), CHỈ nhận nếu cột đó không
 *            nằm bên trái vùng của năm target. Không có luật này thì mấy cột ẩn
 *            C..H (tháng của năm cũ, nhãn trống năm) sẽ nuốt mất tháng 7/8 và
 *            script ghi số vào cột ẩn — nhìn ngoài tưởng nó không chạy.
 */
function buildMonthColumnMap_(sheet, blocks, year) {
  var map = {};
  var minExplicitCol = null;

  blocks.forEach(function (b) {
    var labels = readHeaderRow_(sheet, b.headerRow);
    for (var i = 0; i < labels.length; i++) {
      var parsed = parseMonthLabel_(labels[i]);
      if (!parsed || !parsed.year || parsed.year !== year) continue;
      var col = CONFIG.FIRST_MONTH_COL + i;
      if (!map[parsed.month]) map[parsed.month] = col;
      if (minExplicitCol === null || col < minExplicitCol) minExplicitCol = col;
    }
  });

  var floor = minExplicitCol === null ? CONFIG.FIRST_MONTH_COL : minExplicitCol;
  blocks.forEach(function (b) {
    var labels = readHeaderRow_(sheet, b.headerRow);
    for (var i = 0; i < labels.length; i++) {
      var parsed = parseMonthLabel_(labels[i]);
      if (!parsed || parsed.year) continue;          // đã xử ở lượt 1
      var col = CONFIG.FIRST_MONTH_COL + i;
      if (col < floor) continue;                     // cột của năm cũ → bỏ
      if (!map[parsed.month]) map[parsed.month] = col;
    }
  });
  return map;
}

function readHeaderRow_(sheet, row) {
  // Clamp theo số cột thật của sheet — đọc quá biên là Apps Script văng lỗi
  // "out of bounds" và cả lần chạy chết ngay, không ghi được ô nào.
  var lastCol = Math.min(CONFIG.MAX_SCAN_COL, sheet.getMaxColumns());
  var n = lastCol - CONFIG.FIRST_MONTH_COL + 1;
  if (n <= 0) return [];
  return sheet.getRange(row, CONFIG.FIRST_MONTH_COL, 1, n).getValues()[0];
}

/** "July - 2026 (1st-27th)" → {month: 7, year: 2026}. "Total"/rỗng → null. */
function parseMonthLabel_(label) {
  // Header nhập kiểu ngày (Google Sheets tự đổi "Aug 2026" thành Date) →
  // getValue() trả Date chứ không phải chữ, phải bắt riêng.
  if (label instanceof Date) return { month: label.getMonth() + 1, year: label.getFullYear() };
  var s = norm_(label);
  if (!s || s.indexOf('total') === 0) return null;
  var m = s.match(/^([a-z]{3,9})/);
  if (!m) return null;
  var idx = -1;
  for (var i = 0; i < 12; i++) {
    if (m[1].indexOf(MONTH_ABBR[i]) === 0) { idx = i; break; }
  }
  if (idx < 0) return null;
  var y = s.match(/(20\d{2})/);
  return { month: idx + 1, year: y ? Number(y[1]) : null };
}


/**
 * Kéo công thức của cột tháng TRƯỚC sang cột tháng m, cho những ô đang trống.
 *  - Chủ yếu để cứu bảng TOTAL CHANNEL: nó sống bằng công thức của sheet, cột
 *    mới chèn thì trống nên nhìn như bảng tổng không có tháng mới.
 *  - copyTo() tự dịch tham chiếu tương đối (=C4+C15+C24 → =P4+P15+P24).
 *  - KHÔNG bao giờ đè ô đã có sẵn nội dung.
 * Trả về số ô đã kéo.
 */
function copyFormulaColumn_(sheet, block, m, col, monthCol, year, curMonth, target) {
  var prevCol = nearestPrevMonthCol_(monthCol, col);
  if (!prevCol) return 0;

  // Nhãn header: bắt chước kiểu chữ của chính bảng đó ("Jan - 2026" vs "Jan").
  var head = sheet.getRange(block.headerRow, col);
  if (String(head.getValue() || '').trim() === '') {
    var suffix = (m === curMonth) ? partialSuffixAny_(year, m, target) : '';
    head.setValue(labelLike_(sheet.getRange(block.headerRow, prevCol).getValue(), m, year) + suffix);
  }

  var copied = 0;
  var rowList = [];
  for (var k in block.rows) rowList.push(block.rows[k]);
  rowList.sort(function (a, b) { return a - b; });

  rowList.forEach(function (r) {
    var dest = sheet.getRange(r, col);
    if (String(dest.getValue() || '') !== '') return;      // đã có số/công thức
    var srcCell = sheet.getRange(r, prevCol);
    if (String(srcCell.getFormula() || '') === '') return; // cột trước cũng không có công thức
    srcCell.copyTo(dest);
    copied++;
  });
  return copied;
}

/**
 * Dựng công thức cho bảng TOTAL CHANNEL ở cột `col`:
 *   Spent/Leads/Booking/Revenue = cộng dọc 3 bảng platform (=P4+P15+P24)
 *   ROAS = Revenue / Spent của chính bảng tổng
 *   Cost per lead = Spent / Leads của chính bảng tổng
 * Chỉ ghi vào ô ĐANG TRỐNG. Trả về số ô đã dựng.
 */
function buildTotalFormulas_(sheet, blocks, block, col) {
  var platforms = blocks.filter(function (b) { return !!b.platform; });
  if (!platforms.length) return 0;
  var a1 = colLetter_(sheet, col);
  var built = 0;

  ['spend', 'leads', 'booking', 'revenue'].forEach(function (k) {
    var r = block.rows[k];
    if (!r) return;
    var dest = sheet.getRange(r, col);
    if (String(dest.getValue() || '') !== '') return;
    var parts = [];
    platforms.forEach(function (b) { if (b.rows[k]) parts.push(a1 + b.rows[k]); });
    if (!parts.length) return;
    dest.setFormula('=' + parts.join('+'));
    built++;
  });

  if (block.rows.roas && block.rows.spend && block.rows.revenue) {
    var roasCell = sheet.getRange(block.rows.roas, col);
    if (String(roasCell.getValue() || '') === '') {
      roasCell.setFormula('=IF(' + a1 + block.rows.spend + '=0,0,' +
                          a1 + block.rows.revenue + '/' + a1 + block.rows.spend + ')');
      built++;
    }
  }
  if (CONFIG.WRITE_COST_PER_LEAD && setCostPerLead_(sheet, block, col, a1)) built++;
  return built;
}

/**
 * Đặt công thức Cost per lead = Spent / Leads cho 1 bảng ở cột `col`.
 * Chỉ ghi khi ô đang trống hoặc đang là công thức — số gõ tay thì để yên.
 */
function setCostPerLead_(sheet, block, col, a1) {
  if (!block.rows.cpl || !block.rows.leads || !block.rows.spend) return false;
  var cell = sheet.getRange(block.rows.cpl, col);
  var cur = String(cell.getValue() || '');
  if (cur !== '' && String(cell.getFormula() || '') === '') return false;  // số nhập tay
  cell.setFormula('=IF(' + a1 + block.rows.leads + '=0,"",' +
                  a1 + block.rows.spend + '/' + a1 + block.rows.leads + ')');
  return true;
}

/** Cột tháng gần nhất nằm bên trái cột `col`. */
function nearestPrevMonthCol_(monthCol, col) {
  var best = null;
  for (var m in monthCol) {
    var c = monthCol[m];
    if (c >= col) continue;
    if (best === null || c > best) best = c;
  }
  return best;
}

/**
 * Nới công thức =SUM(C4:O4) ở cột "Total" để ôm hết cột tháng.
 * Chỉ đụng vào SUM 1 dải, cùng dòng — mọi công thức khác (ROAS tổng =Q8/Q4…)
 * để nguyên, không đoán mò. Trả về số công thức đã sửa.
 */
function extendTotalSum_(sheet, block, monthCol) {
  var totalCol = findTotalCol_(sheet, block);
  if (!totalCol) return 0;

  var first = null, last = null;
  for (var m in monthCol) {
    var c = monthCol[m];
    if (c >= totalCol) continue;                 // cột tháng phải nằm trước Total
    if (first === null || c < first) first = c;
    if (last === null || c > last) last = c;
  }
  if (first === null) return 0;

  var firstA1 = colLetter_(sheet, first);
  var lastA1 = colLetter_(sheet, last);
  var fixed = 0;

  for (var k in block.rows) {
    var r = block.rows[k];
    var cell = sheet.getRange(r, totalCol);
    var f = String(cell.getFormula() || '');
    var mm = f.match(/^=SUM\(([A-Z]+)(\d+):([A-Z]+)(\d+)\)$/i);
    if (!mm) continue;                           // không phải SUM 1 dải → bỏ
    if (Number(mm[2]) !== r || Number(mm[4]) !== r) continue;  // SUM dọc → bỏ
    var want = '=SUM(' + firstA1 + r + ':' + lastA1 + r + ')';
    if (f.toUpperCase() === want.toUpperCase()) continue;
    cell.setFormula(want);
    fixed++;
  }
  return fixed;
}

function findTotalCol_(sheet, block) {
  var labels = readHeaderRow_(sheet, block.headerRow);
  for (var i = 0; i < labels.length; i++) {
    if (norm_(labels[i]).indexOf('total') === 0) return CONFIG.FIRST_MONTH_COL + i;
  }
  return null;
}

/**
 * Tạo nhãn tháng theo đúng kiểu của nhãn mẫu:
 *   "June - 2026"      → "July - 2026"
 *   "Jun"              → "Jul"
 *   "Jul (1st-27th)"   → "Aug"      (đuôi partial do chỗ gọi tự gắn)
 */
function labelLike_(sample, m, year) {
  var s = String(sample instanceof Date ? '' : (sample || '')).trim();
  var word = MONTH_FULL[m - 1];
  var wordMatch = s.match(/^([A-Za-z]+)/);
  // Chỉ coi là viết tắt khi mẫu đúng 3 chữ ("Jul", "Aug"). "June"/"July" là tên
  // đầy đủ, đừng cắt thành "Jun"/"Jul" rồi làm lệch kiểu chữ của bảng.
  if (wordMatch && wordMatch[1].length === 3) word = MONTH_FULL[m - 1].slice(0, 3);
  return /20\d{2}/.test(s) ? word + ' - ' + year : word;
}

/** Ngày data cuối cùng tính trên MỌI platform — dùng cho bảng tổng. */
function partialSuffixAny_(year, month, target) {
  var day = 0;
  PLATFORMS.forEach(function (p) {
    var d = lastDataDay_(year, month, p.key, target);
    if (d && d > day) day = d;
  });
  return day ? ' (1st-' + ordinal_(day) + ')' : '';
}


/** Chèn 1 cột mới ngay sau cột tháng cuối cùng. Trả về index cột mới. */
function insertMonthColumn_(sheet, monthCol) {
  var last = CONFIG.FIRST_MONTH_COL;
  for (var m in monthCol) if (monthCol[m] > last) last = monthCol[m];
  sheet.insertColumnAfter(last);         // kế thừa format của cột bên trái
  return last + 1;
}


/**
 * Ghi/cập nhật nhãn header của 1 block cho tháng m.
 *  - ô trống        → ghi nhãn đầy đủ "August - 2026"
 *  - tháng hiện tại → gắn "(1st-Nth)" theo ngày cuối cùng có data
 *  - tháng đã đủ data cả tháng → gỡ đuôi "(1st-Nth)" cho sạch
 */
function writeHeaderLabel_(sheet, block, m, col, monthCol, year, curMonth, platformKey, target) {
  var cell = sheet.getRange(block.headerRow, col);
  var current = String(cell.getValue() || '').trim();
  var isCurrent = (m === curMonth);

  if (!current) {
    // Bắt chước kiểu chữ của chính bảng đó: "June - 2026" → "July - 2026",
    // còn "Jul (1st-27th)" → "Aug". Không ép mọi tab về một kiểu.
    var prevCol = nearestPrevMonthCol_(monthCol, col);
    var sample = prevCol ? sheet.getRange(block.headerRow, prevCol).getValue() : '';
    var base = labelLike_(sample, m, year);
    cell.setValue(isCurrent ? base + partialSuffix_(year, m, platformKey, target) : base);
    return;
  }
  if (!CONFIG.UPDATE_PARTIAL_LABEL) return;

  var PARTIAL_RE = /\s*\(1st-\d+(st|nd|rd|th)\)\s*$/i;
  if (!isCurrent) {
    // Tháng cũ: chỉ đụng vào khi nhãn đang mang đuôi "(1st-Nth)" và data đã
    // đủ cả tháng — lúc đó gỡ đuôi. Còn thiếu ngày thì để nguyên cho khỏi lừa.
    if (!CONFIG.FINALIZE_PAST_LABELS || !PARTIAL_RE.test(current)) return;
    var day = lastDataDay_(year, m, platformKey, target);
    if (day && day >= daysInMonth_(year, m)) cell.setValue(current.replace(PARTIAL_RE, ''));
    return;
  }

  var suffix = partialSuffix_(year, m, platformKey, target);
  if (!suffix) return;
  cell.setValue(current.replace(PARTIAL_RE, '').trim() + suffix);
}

/** " (1st-27th)" dựa trên ngày cuối cùng có spend trong tháng, '' nếu không rõ. */
function partialSuffix_(year, month, platformKey, target) {
  var day = lastDataDay_(year, month, platformKey, target);
  return day ? ' (1st-' + ordinal_(day) + ')' : '';
}

/**
 * Rows thô của /spend/daily cho (năm, tháng, platform) — cache dùng chung cho
 * mọi target, vì lọc branch làm ở phía script chứ không phải ở API.
 */
var _dailyCache = {};
function fetchDailyRows_(year, month, platformKey) {
  var key = year + '-' + month + '-' + platformKey;
  if (_dailyCache[key] !== undefined) return _dailyCache[key];

  var mm = (month < 10 ? '0' : '') + month;
  var from = year + '-' + mm + '-01';
  var to = year + '-' + mm + '-' + daysInMonth_(year, month);
  var rows = [];
  try {
    rows = adsGet_('/api/export/spend/daily?date_from=' + from + '&date_to=' + to +
                   '&platform=' + platformKey + '&valid_country_only=true').data || [];
  } catch (e) {
    Logger.log('Không lấy được ngày data cuối: ' + e);
  }
  _dailyCache[key] = rows;
  return rows;
}

var _lastDayCache = {};
function lastDataDay_(year, month, platformKey, target) {
  var key = year + '-' + month + '-' + platformKey + '-' + target.sheetName;
  if (_lastDayCache[key] !== undefined) return _lastDayCache[key];

  var rows = fetchDailyRows_(year, month, platformKey);
  var day = 0;
  rows.forEach(function (r) {
    if (Number(r.spend || 0) <= 0) return;
    if (!branchAllowed_(r.branch, target)) return;
    var d = Number(String(r.date).slice(8, 10));
    if (d > day) day = d;
  });
  _lastDayCache[key] = day || null;
  return _lastDayCache[key];
}


// ===================== Ads Platform API =====================

/**
 * { 1..12: {spend, revenue, conversions} } — cộng các branch của target.
 * Raw JSON cache theo (năm, platform) nên 2 tab dùng chung 1 call API.
 */
function fetchPlatformMonths_(year, platformKey, target) {
  var branches = fetchPlatformRaw_(year, platformKey);
  var native = target.currency === 'NATIVE';
  var out = {};
  for (var m = 1; m <= 12; m++) out[m] = { spend: 0, revenue: 0, conversions: 0, leads: 0 };

  branches.forEach(function (b) {
    if (!branchAllowed_(b.branch, target)) return;
    (b.months || []).forEach(function (row) {
      var bucket = out[row.month];
      if (!bucket) return;
      bucket.spend += Number((native ? row.spend_native : row.spend_vnd) || 0);
      bucket.revenue += Number((native ? row.revenue_native : row.revenue_vnd) || 0);
      bucket.conversions += Number(row.conversions || 0);
      bucket.leads += Number(row.leads || 0);   // API cũ chưa có field này → 0
    });
  });
  return out;
}

var _rawCache = {};
function fetchPlatformRaw_(year, platformKey) {
  var key = year + '-' + platformKey;
  if (_rawCache[key]) return _rawCache[key];
  var json = adsGet_('/api/export/kpi/paid-ads-monthly?year=' + year +
                     '&platform=' + encodeURIComponent(platformKey));
  _rawCache[key] = (json.data && json.data.branches) || [];
  return _rawCache[key];
}

/** Branch có được tính vào target này không (onlyBranches / excludeBranches). */
function branchAllowed_(branch, target) {
  var b = norm_(branch);
  var only = target.onlyBranches || [];
  if (only.length) {
    for (var i = 0; i < only.length; i++) if (norm_(only[i]) === b) return true;
    return false;
  }
  var skip = target.excludeBranches || [];
  for (var j = 0; j < skip.length; j++) if (norm_(skip[j]) === b) return false;
  return true;
}

function branchScopeText_(target) {
  return (target.onlyBranches || []).length
    ? 'chỉ ' + target.onlyBranches.join(',')
    : 'tất cả trừ ' + ((target.excludeBranches || []).join(',') || '(không trừ ai)');
}

function adsGet_(path) {
  var url = CONFIG.ADS_BASE_URL.replace(/\/+$/, '') + path;
  var resp = UrlFetchApp.fetch(url, {
    method: 'get',
    headers: { 'X-API-Key': CONFIG.ADS_API_KEY },
    muteHttpExceptions: true,
  });
  var code = resp.getResponseCode();
  var body = resp.getContentText();
  if (code !== 200) throw new Error('Ads API HTTP ' + code + ': ' + body.slice(0, 400));
  var json = JSON.parse(body);
  if (json.success === false) throw new Error('Ads API error: ' + (json.error || 'unknown'));
  return json;
}


// ======================== Helpers ========================

function norm_(v) { return String(v == null ? '' : v).trim().toLowerCase(); }

function label_(block, m) {
  return (block.platform || '?').toUpperCase() + ' ' + MONTH_FULL[m - 1];
}

function colLetter_(sheet, col) {
  return sheet.getRange(1, col).getA1Notation().replace(/\d+$/, '');
}

function fmt_(n) { return String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ','); }

function daysInMonth_(year, month) { return new Date(year, month, 0).getDate(); }

function ordinal_(d) {
  if (d % 100 >= 11 && d % 100 <= 13) return d + 'th';
  return d + (['th', 'st', 'nd', 'rd'][d % 10] || 'th');
}

function toast_(msg) {
  try { SpreadsheetApp.getActive().toast(msg, 'Ads Sync', 6); } catch (e) { Logger.log(msg); }
}


// ======================== Debug ========================

/**
 * In ra HẾT mọi thứ script nhìn thấy cho TỪNG tab, để biết tắc ở đâu:
 *   (a) tab/bảng không dò được, (b) không có cột cho tháng đó,
 *   (c) API trả 0 (→ lỗi sync bên platform, không phải lỗi sheet).
 */
function debugCheck() {
  var now = new Date();
  var year = CONFIG.YEAR || now.getFullYear();
  var curMonth = (year === now.getFullYear()) ? now.getMonth() + 1 : 12;
  var out = ['Hôm nay: ' + now.toDateString(),
             'Năm target: ' + year + ' | tháng hiện tại: ' + curMonth, ''];

  CONFIG.TARGETS.forEach(function (target) {
    out.push('##### ' + target.name + ' — "' + target.sheetName + '"' +
             (target.enabled === false ? ' (ĐANG TẮT)' : '') + ' #####');
    out.push('Branch: ' + branchScopeText_(target) +
             ' | tiền: ' + (target.currency === 'NATIVE' ? 'native' : 'VND'));

    var sheet = SpreadsheetApp.getActive().getSheetByName(target.sheetName);
    if (!sheet) { out.push('❌ Không thấy tab này.'); out.push(''); return; }

    // 1. Bảng dò được
    var blocks = findBlocks_(sheet);
    out.push('--- BẢNG DÒ ĐƯỢC (' + blocks.length + ') ---');
    blocks.forEach(function (b) {
      out.push('• ' + (b.platform || '(không nhận ra platform → bỏ qua)') +
               ' | header dòng ' + b.headerRow + ' | rows: ' + JSON.stringify(b.rows));
    });

    // 2. Nhãn header + map tháng → cột
    out.push('--- NHÃN HEADER ---');
    blocks.forEach(function (b) {
      var labels = readHeaderRow_(sheet, b.headerRow);
      var seen = [];
      for (var i = 0; i < labels.length; i++) {
        var v = labels[i];
        if (v === '' || v === null) continue;
        var parsed = parseMonthLabel_(v);
        seen.push(colLetter_(sheet, CONFIG.FIRST_MONTH_COL + i) + '="' +
                  (v instanceof Date ? v.toDateString() + ' (kiểu Date)' : v) + '"' +
                  (parsed ? ' → ' + parsed.month + '/' + (parsed.year || '?') : ' → không phải tháng'));
      }
      out.push('• ' + (b.platform || 'TOTAL') + ' (dòng ' + b.headerRow + '): ' + seen.join(' | '));
    });
    var map = buildMonthColumnMap_(sheet, blocks, year);
    var mapTxt = [];
    for (var m = 1; m <= 12; m++) if (map[m]) mapTxt.push(m + '→' + colLetter_(sheet, map[m]));
    out.push('Map tháng→cột (' + year + '): ' + (mapTxt.join(', ') || 'TRỐNG'));
    out.push(map[curMonth]
      ? 'Tháng ' + curMonth + ' nằm ở cột ' + colLetter_(sheet, map[curMonth])
      : '⚠️ KHÔNG có cột nào cho tháng ' + curMonth +
        (CONFIG.AUTO_ADD_COLUMN ? ' → script sẽ chèn cột mới.' : ' → AUTO_ADD_COLUMN đang tắt!'));

    // 3. API trả gì cho tháng hiện tại
    out.push('--- API (tháng ' + curMonth + ') ---');
    var native = target.currency === 'NATIVE';
    PLATFORMS.forEach(function (p) {
      var branches;
      try {
        branches = fetchPlatformRaw_(year, p.key);
      } catch (e) {
        out.push('• ' + p.key + ': LỖI GỌI API — ' + e);
        return;
      }
      var tot = { spend: 0, revenue: 0, conversions: 0 };
      var lines = [];
      branches.forEach(function (b) {
        var row = null;
        (b.months || []).forEach(function (r) { if (r.month === curMonth) row = r; });
        if (!row) { lines.push('    - ' + b.branch + ': không có dòng tháng này'); return; }
        var sp = Number((native ? row.spend_native : row.spend_vnd) || 0);
        var rv = Number((native ? row.revenue_native : row.revenue_vnd) || 0);
        var ok = branchAllowed_(b.branch, target);
        if (ok) { tot.spend += sp; tot.revenue += rv; tot.conversions += Number(row.conversions || 0); }
        lines.push('    - ' + b.branch + (ok ? '' : ' [LOẠI]') + ': spend ' + fmt_(sp) +
                   ' | conv ' + row.conversions + ' | rev ' + fmt_(rv));
      });
      out.push('• ' + p.key.toUpperCase() + ' → TỔNG spend ' + fmt_(tot.spend) +
               ' | booking ' + tot.conversions + ' | revenue ' + fmt_(tot.revenue));
      out = out.concat(lines);
      if (tot.spend === 0 && tot.revenue === 0) {
        out.push('    ⚠️ Tất cả = 0. Không phải lỗi script — data tháng này chưa có' +
                 ' trong metrics_cache. Kiểm tra sync của platform này' +
                 ' (token chết là cron vẫn xanh nhưng số đứng im).');
      }
      var day = lastDataDay_(year, curMonth, p.key, target);
      out.push('    Ngày cuối cùng có spend: ' + (day ? year + '-' + curMonth + '-' + day : 'KHÔNG CÓ NGÀY NÀO'));
    });
    out.push('');
  });

  alertLong_('Ads Sync — debug', out.join('\n'));
}

/** Alert có giới hạn ký tự — luôn log full ra Executions. */
function alertLong_(title, body) {
  Logger.log(body);
  var shown = body.length > 8000 ? body.slice(0, 8000) + '\n\n…(xem full ở Executions log)' : body;
  SpreadsheetApp.getUi().alert(title, shown, SpreadsheetApp.getUi().ButtonSet.OK);
}


// ===================== Lịch tự chạy =====================

function installDailyTrigger() {
  removeDailyTrigger();
  ScriptApp.newTrigger('syncCampaignReport').timeBased().everyDays(1).atHour(8).create();
  toast_('Đã đặt lịch tự chạy mỗi sáng ~8h.');
}

function removeDailyTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'syncCampaignReport') ScriptApp.deleteTrigger(t);
  });
}
