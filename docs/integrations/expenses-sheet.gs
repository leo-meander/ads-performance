/**
 * GROWTH TEAM — Expenses Record auto-sync (COMBINED)
 * ==================================================
 * Một script kéo CẢ HAI nguồn về thẳng bảng Expenses Record:
 *   • Meta / Google / TikTok  ← Ads Platform  (/api/export/budget/channel-monthly)
 *   • KOL  / CRM              ← HiD Dashboard (/api/marketing-budget/yearly)
 *
 * Tất cả đã là VND. Designer + mọi thứ khác: KHÔNG đụng — nhập tay như cũ.
 *
 * MÔ HÌNH "BLOCK" (để sort được):
 *   - Toàn bộ từ dòng FILL_START_ROW (A109) trở XUỐNG là vùng do script quản.
 *   - Mỗi lần chạy: xoá sạch A109→cuối (cột A–G) → fetch 2 nguồn → gộp →
 *     SORT (năm → tháng → branch → channel) → ghi lại từ A109.
 *   - => Idempotent (chạy lại không nhân đôi), Actual tự cập nhật, luôn sorted.
 *   ⚠️ Dữ liệu NHẬP TAY phải nằm TRÊN dòng 109 (sẽ không bị động tới).
 *
 * CÁCH DÙNG:
 *   1. Google Sheet → Extensions → Apps Script → dán file này.
 *   2. Sửa CONFIG: ADS_BASE_URL, ADS_API_KEY, HID_BASE_URL, SHEET_NAME.
 *      - ADS_API_KEY: admin tạo ở platform (POST /api/export/keys) — hiện 1 lần.
 *   3. Lưu, reload Sheet → menu "Expenses Sync" xuất hiện.
 *   4. Bấm "Expenses Sync → Kéo tất cả (Ads + HiD)" để chạy lần đầu.
 *   5. (Tuỳ chọn) "Đặt lịch tự chạy mỗi sáng".
 */

// ============================ CONFIG ============================
var CONFIG = {
  SHEET_NAME: 'Campaign report +looker',  // tab chứa bảng Expenses Record
  FILL_START_ROW: 109,                    // bắt đầu ghi từ A109

  // ---- Ads Platform (Meta / Google / TikTok) ----
  ADS_BASE_URL: 'https://REPLACE-WITH-ADS-BACKEND',   // KHÔNG có / ở cuối
  ADS_API_KEY:  'REPLACE-WITH-X-API-KEY',
  ADS_START_YEAR: 2026,
  ADS_START_MONTH: 3,                     // 3 = March

  // ---- HiD Dashboard (KOL / CRM) ----
  HID_BASE_URL: 'https://meander-hid-dashboard.zeabur.app',
  HID_START_YEAR: 2026,
  HID_START_MONTH: 4,                     // 4 = April
  HID_CHANNELS: ['kol', 'crm'],           // HiD còn có 'paid_ads' — bỏ qua

  // Nhãn channel ghi vào cột "Chanel".
  CHANNEL_LABEL: {
    meta: 'Meta', google: 'Google', tiktok: 'TikTok', kol: 'KOL', crm: 'CRM',
  },

  // Tên branch HiD -> tên ngắn trong bảng (Ads Platform đã trả tên ngắn sẵn).
  BRANCH_RENAME: {
    'MEANDER Saigon': 'Saigon',
    'MEANDER Osaka':  'Osaka',
    'MEANDER 1948':   '1948',
    'MEANDER Taipei': 'Taipei',
    'MEANDER Oani':   'Oani',
  },

  // Chỉ ghi các branch này (phải khớp data validation ở cột Branch của sheet).
  // Bread (nhà hàng) bị loại vì sheet không cho. Để [] nếu muốn ghi hết.
  BRANCH_WHITELIST: ['Saigon', 'Osaka', '1948', 'Taipei', 'Oani'],

  // Thứ tự sort (sau khi đã xếp theo năm → tháng).
  BRANCH_ORDER:  ['Saigon', 'Osaka', '1948', 'Taipei', 'Oani', 'Bread'],
  CHANNEL_ORDER: ['Meta', 'Google', 'TikTok', 'KOL', 'CRM'],

  MONTH_FORMAT: 'M//YYYY',     // khớp dữ liệu cũ "4//2026". Đổi 'MM/YYYY' nếu muốn "04/2026".
  VND_FORMAT: '#,##0" ₫"',     // 1,234,567 ₫
  PCT_FORMAT: '0.00%',
  SKIP_EMPTY: true,            // bỏ dòng cả Allocate lẫn Actual = 0
};

// Layout cột cố định của bảng: A..G
var COL = { month: 1, year: 2, branch: 3, channel: 4, alloc: 5, actual: 6, pct: 7 };
// ===============================================================


function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Expenses Sync')
    .addItem('Kéo tất cả (Ads + HiD)', 'syncExpenses')
    .addSeparator()
    .addItem('Xem tên branch trong HiD', 'showHidBranches')
    .addItem('Đặt lịch tự chạy mỗi sáng', 'installDailyTrigger')
    .addItem('Xoá lịch tự chạy', 'removeDailyTrigger')
    .addToUi();
}


/** Hàm chính: kéo Ads + HiD, gộp, sort, ghi từ A109. */
function syncExpenses() {
  var sheet = SpreadsheetApp.getActive().getSheetByName(CONFIG.SHEET_NAME);
  if (!sheet) {
    throw new Error('Không thấy tab "' + CONFIG.SHEET_NAME + '". Sửa SHEET_NAME trong CONFIG.');
  }

  var now = new Date();
  var curY = now.getFullYear();
  var curM = now.getMonth() + 1;

  var minYear = Math.min(CONFIG.ADS_START_YEAR, CONFIG.HID_START_YEAR);
  var years = [];
  for (var y = minYear; y <= curY; y++) years.push(y);

  var raw = [];

  // ---- Ads Platform: Meta / Google / TikTok ----
  years.forEach(function (yr) {
    fetchAdsRows_(yr).forEach(function (r) {
      if (!withinCutoff_(r.year, r.monthNum, CONFIG.ADS_START_YEAR, CONFIG.ADS_START_MONTH)) return;
      if (afterNow_(r.year, r.monthNum, curY, curM)) return;
      raw.push(r);
    });
  });

  // ---- HiD Dashboard: KOL / CRM ----
  var branches = fetchBranches_();
  years.forEach(function (yr) {
    fetchHidRows_(yr, branches).forEach(function (r) {
      if (!withinCutoff_(r.year, r.monthNum, CONFIG.HID_START_YEAR, CONFIG.HID_START_MONTH)) return;
      if (afterNow_(r.year, r.monthNum, curY, curM)) return;
      raw.push(r);
    });
  });

  // Lọc branch ngoài whitelist (tránh đụng data validation) + dòng rỗng.
  var allow = CONFIG.BRANCH_WHITELIST || [];
  var rows = raw.filter(function (r) {
    if (allow.length && allow.indexOf(r.branch) < 0) return false;
    return !(CONFIG.SKIP_EMPTY && r.alloc === 0 && r.actual === 0);
  });
  rows.forEach(function (r) { r.pct = r.alloc > 0 ? r.actual / r.alloc : ''; });

  sortRows_(rows);

  // Xoá block cũ rồi ghi mới.
  clearBlock_(sheet);

  if (rows.length === 0) {
    toast_('HiD/Ads chưa có dữ liệu trong khoảng này.');
    return;
  }

  var start = CONFIG.FILL_START_ROW;
  var values = rows.map(function (r) {
    return [formatMonth_(r.monthNum, r.year), r.year, r.branch, r.channel, r.alloc, r.actual, r.pct];
  });
  sheet.getRange(start, 1, values.length, 7).setValues(values);
  sheet.getRange(start, COL.alloc, values.length, 2).setNumberFormat(CONFIG.VND_FORMAT);
  sheet.getRange(start, COL.pct, values.length, 1).setNumberFormat(CONFIG.PCT_FORMAT);

  var adsN = rows.filter(function (r) { return ['Meta', 'Google', 'TikTok'].indexOf(r.channel) >= 0; }).length;
  toast_('Đã ghi ' + rows.length + ' dòng (Ads ' + adsN + ' + HiD ' + (rows.length - adsN) + ') từ A' + start + '.');
}


/** Xoá nội dung A–G từ FILL_START_ROW xuống hết. */
function clearBlock_(sheet) {
  var start = CONFIG.FILL_START_ROW;
  var last = sheet.getLastRow();
  if (last < start) return;
  sheet.getRange(start, 1, last - start + 1, 7).clearContent();
}


/** Sort: năm → tháng → branch (theo BRANCH_ORDER) → channel (theo CHANNEL_ORDER). */
function sortRows_(rows) {
  rows.sort(function (a, b) {
    if (a.year !== b.year) return a.year - b.year;
    if (a.monthNum !== b.monthNum) return a.monthNum - b.monthNum;
    var bi = orderIndex_(CONFIG.BRANCH_ORDER, a.branch) - orderIndex_(CONFIG.BRANCH_ORDER, b.branch);
    if (bi !== 0) return bi;
    return orderIndex_(CONFIG.CHANNEL_ORDER, a.channel) - orderIndex_(CONFIG.CHANNEL_ORDER, b.channel);
  });
}

function orderIndex_(arr, val) {
  var i = arr.indexOf(val);
  return i < 0 ? 999 : i;
}


// ===================== Ads Platform API =====================

/** Trả mảng {year, monthNum, branch, channel, alloc, actual} cho 1 năm. */
function fetchAdsRows_(year) {
  var json = adsGet_('/api/export/budget/channel-monthly?year=' + encodeURIComponent(year));
  var rows = (json.data && json.data.rows) || [];
  return rows.map(function (r) {
    return {
      year: r.year,
      monthNum: r.month,
      branch: r.branch,  // Ads Platform đã trả tên ngắn (Saigon/Osaka/1948/...)
      channel: CONFIG.CHANNEL_LABEL[r.channel_key] || r.channel,
      alloc: Math.round(Number(r.allocate_vnd || 0)),
      actual: Math.round(Number(r.spend_vnd || 0)),
    };
  });
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


// ======================== HiD API ========================

/** Trả mảng {year, monthNum, branch, channel, alloc, actual} KOL/CRM cho 1 năm. */
function fetchHidRows_(year, branches) {
  var out = [];
  branches.forEach(function (b) {
    var data = fetchHidYearly_(b.id, year);
    if (!data || !data.months) return;
    for (var m = 1; m <= 12; m++) {
      var monthObj = data.months[m - 1];
      if (!monthObj || !monthObj.channels) continue;
      CONFIG.HID_CHANNELS.forEach(function (chKey) {
        var ch = monthObj.channels.filter(function (c) { return c.channel === chKey; })[0];
        if (!ch) return;
        out.push({
          year: year,
          monthNum: m,
          branch: renameBranch_(b.name),
          channel: CONFIG.CHANNEL_LABEL[chKey] || chKey,
          alloc: Math.round(Number(ch.allocated_vnd || 0)),
          actual: Math.round(Number(ch.actual_vnd || 0)),
        });
      });
    }
  });
  return out;
}

function fetchBranches_() {
  var json = hidGet_('/api/branches');
  return (json.data || []).map(function (b) { return { id: b.id, name: b.name }; });
}

function fetchHidYearly_(branchId, year) {
  var json = hidGet_('/api/marketing-budget/yearly?branch_id=' + encodeURIComponent(branchId) + '&year=' + year);
  return json.data;
}

function hidGet_(path) {
  var url = CONFIG.HID_BASE_URL.replace(/\/+$/, '') + path;
  var resp = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
  var code = resp.getResponseCode();
  if (code !== 200) throw new Error('HiD API HTTP ' + code + ' (' + url + '): ' + resp.getContentText().slice(0, 300));
  var json = JSON.parse(resp.getContentText());
  if (json.success === false) throw new Error('HiD error: ' + (json.error || 'unknown') + ' (' + url + ')');
  return json;
}


// ======================== Helpers ========================

function withinCutoff_(year, month, startYear, startMonth) {
  return year > startYear || (year === startYear && month >= startMonth);
}

function afterNow_(year, month, curY, curM) {
  return year > curY || (year === curY && month > curM);
}

function formatMonth_(month, year) {
  if (CONFIG.MONTH_FORMAT === 'MM/YYYY') {
    return (month < 10 ? '0' + month : '' + month) + '/' + year;
  }
  return month + '//' + year;
}

function renameBranch_(name) {
  return CONFIG.BRANCH_RENAME[name] || name;
}

function toast_(msg) {
  try { SpreadsheetApp.getActive().toast(msg, 'Expenses Sync', 6); } catch (e) { Logger.log(msg); }
}


// ===================== Tiện ích / lịch =====================

function showHidBranches() {
  var branches = fetchBranches_();
  var msg = branches.map(function (b) { return '• ' + b.name; }).join('\n');
  SpreadsheetApp.getUi().alert('Branch trong HiD:\n\n' + msg);
}

function installDailyTrigger() {
  removeDailyTrigger();
  ScriptApp.newTrigger('syncExpenses').timeBased().everyDays(1).atHour(7).create();
  toast_('Đã đặt lịch tự chạy mỗi sáng ~7h.');
}

function removeDailyTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'syncExpenses') ScriptApp.deleteTrigger(t);
  });
}
