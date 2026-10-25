import { importPlace } from './maps.js';
import { planTrip } from './plan.js';

const MAX_ITEMS = 60;
const ALPHABET = 'abcdefghijkmnpqrstuvwxyz23456789'; // 去掉容易混淆的 l o 0 1

const json = (data, status = 200) => Response.json(data, { status, headers: { 'cache-control': 'no-store' } });
const fail = (msg, status = 400) => json({ error: msg }, status);

function randomId(len) {
  const b = crypto.getRandomValues(new Uint8Array(len));
  return Array.from(b, (x) => ALPHABET[x % ALPHABET.length]).join('');
}

const clean = (s, n) => String(s ?? '').trim().slice(0, n);
const int = (v, lo, hi, d) => {
  const n = Number.parseInt(v, 10);
  return Number.isFinite(n) ? Math.min(hi, Math.max(lo, n)) : d;
};

async function loadTrip(env, id) {
  const trip = await env.DB.prepare('SELECT * FROM trips WHERE id = ?').bind(id).first();
  if (!trip) return null;
  const { results } = await env.DB.prepare(
    'SELECT id, day, position, name, lat, lng, url, note, added_by FROM items WHERE trip_id = ? ORDER BY day, position',
  ).bind(id).all();
  let tips = {};
  try { tips = JSON.parse(trip.tips); } catch { /* 壞資料就當沒有 */ }
  return { id: trip.id, name: trip.name, days: trip.days, version: trip.version, tips, items: results };
}

const bump = (env, id) => env.DB.prepare('UPDATE trips SET version = version + 1 WHERE id = ?').bind(id);

// 依 layout 重寫所有項目的 day/position。layout: { "0": [id...], "1": [id...] }
function layoutStatements(env, tripId, layout) {
  const stmts = [];
  for (const [day, ids] of Object.entries(layout)) {
    ids.forEach((id, pos) =>
      stmts.push(env.DB.prepare('UPDATE items SET day = ?, position = ? WHERE id = ? AND trip_id = ?').bind(+day, pos, id, tripId)));
  }
  return stmts;
}

async function handle(request, env) {
  const url = new URL(request.url);
  const parts = url.pathname.split('/').filter(Boolean); // ['api','trips',id,...]
  const method = request.method;
  if (parts[0] !== 'api' || parts[1] !== 'trips') return null;

  // 建立行程
  if (parts.length === 2 && method === 'POST') {
    const body = await request.json().catch(() => ({}));
    const id = randomId(12);
    await env.DB.prepare('INSERT INTO trips (id, name, days, created_at) VALUES (?, ?, ?, ?)')
      .bind(id, clean(body.name, 40) || '我們的旅行', int(body.days, 1, 14, 5), Date.now()).run();
    return json({ id });
  }

  const tripId = parts[2];
  if (!tripId || !/^[a-z0-9]{12}$/.test(tripId)) return fail('找不到行程', 404);

  // 讀取(帶 v= 目前版本時,沒變動就只回 unchanged,省流量)
  if (parts.length === 3 && method === 'GET') {
    const v = url.searchParams.get('v');
    if (v !== null) {
      const row = await env.DB.prepare('SELECT version FROM trips WHERE id = ?').bind(tripId).first();
      if (!row) return fail('找不到行程', 404);
      if (String(row.version) === v) return json({ unchanged: true });
    }
    const trip = await loadTrip(env, tripId);
    return trip ? json(trip) : fail('找不到行程', 404);
  }

  const exists = await env.DB.prepare('SELECT days FROM trips WHERE id = ?').bind(tripId).first();
  if (!exists) return fail('找不到行程', 404);

  // 修改名稱 / 天數
  if (parts.length === 3 && method === 'PATCH') {
    const body = await request.json().catch(() => ({}));
    const name = clean(body.name, 40);
    const days = body.days != null ? int(body.days, 1, 14, exists.days) : exists.days;
    const stmts = [env.DB.prepare('UPDATE trips SET name = COALESCE(NULLIF(?, \'\'), name), days = ? WHERE id = ?').bind(name, days, tripId)];
    // 天數縮短時,超出的項目退回「尚未安排」
    if (days < exists.days) // position 加大是為了排在原本「尚未安排」的項目後面,且保持彼此順序
    if (days < exists.days) stmts.push(env.DB.prepare('UPDATE items SET day = 0, position = position + 10000 WHERE trip_id = ? AND day > ?').bind(tripId, days));
    stmts.push(bump(env, tripId));
    await env.DB.batch(stmts);
    return json({ ok: true });
  }

  // 加入地點(貼 Google Maps 連結或文字)
  if (parts[3] === 'items' && parts.length === 4 && method === 'POST') {
    const body = await request.json().catch(() => ({}));
    const text = clean(body.text, 600);
    if (!text) return fail('請貼上地點或連結');
    const cnt = await env.DB.prepare('SELECT COUNT(*) AS n FROM items WHERE trip_id = ?').bind(tripId).first();
    if (cnt.n >= MAX_ITEMS) return fail('地點太多了,請先刪除一些');
    let place;
    try { place = await importPlace(text); } catch (e) { return fail(e.message || '連結無法讀取'); }
    if (!place.name) return fail('讀不到地點名稱,請改貼「分享」的連結,或直接輸入地點名稱');
    const id = crypto.randomUUID();
    const last = await env.DB.prepare('SELECT COALESCE(MAX(position), -1) + 1 AS p FROM items WHERE trip_id = ? AND day = 0').bind(tripId).first();
    await env.DB.batch([
      env.DB.prepare('INSERT INTO items (id, trip_id, day, position, name, lat, lng, url, added_by) VALUES (?, ?, 0, ?, ?, ?, ?, ?, ?)')
        .bind(id, tripId, last.p, place.name, place.lat, place.lng, place.url, clean(body.who, 20)),
      bump(env, tripId),
    ]);
    return json({ id, name: place.name });
  }

  // 改單一項目:名稱、備註
  if (parts[3] === 'items' && parts.length === 5 && method === 'PATCH') {
    const body = await request.json().catch(() => ({}));
    const r = await env.DB.batch([
      env.DB.prepare('UPDATE items SET name = COALESCE(NULLIF(?, \'\'), name), note = COALESCE(?, note) WHERE id = ? AND trip_id = ?')
        .bind(clean(body.name, 80), body.note != null ? clean(body.note, 300) : null, parts[4], tripId),
      bump(env, tripId),
    ]);
    return r[0].meta.changes ? json({ ok: true }) : fail('找不到這個地點', 404);
  }

  if (parts[3] === 'items' && parts.length === 5 && method === 'DELETE') {
    await env.DB.batch([
      env.DB.prepare('DELETE FROM items WHERE id = ? AND trip_id = ?').bind(parts[4], tripId),
      bump(env, tripId),
    ]);
    return json({ ok: true });
  }

  // 整份排列(拖曳/移到某天/上移下移,前端算好整份送上來)
  if (parts[3] === 'layout' && method === 'PUT') {
    const body = await request.json().catch(() => ({}));
    const layout = body.layout;
    if (!layout || typeof layout !== 'object') return fail('資料格式不對');
    const { results } = await env.DB.prepare('SELECT id FROM items WHERE trip_id = ?').bind(tripId).all();
    const known = new Set(results.map((r) => r.id));
    const seen = new Set();
    const safe = {};
    for (const [day, ids] of Object.entries(layout)) {
      const d = Number(day);
      if (!Number.isInteger(d) || d < 0 || d > exists.days || !Array.isArray(ids)) return fail('資料格式不對');
      safe[d] = ids.filter((id) => known.has(id) && !seen.has(id) && seen.add(id));
    }
    // 請求裡沒提到的項目一律放回「尚未安排」
    const rest = [...known].filter((id) => !seen.has(id));
    safe[0] = [...(safe[0] || []), ...rest];
    await env.DB.batch([...layoutStatements(env, tripId, safe), bump(env, tripId)]);
    return json({ ok: true });
  }

  // AI 排行程
  if (parts[3] === 'plan' && method === 'POST') {
    const { results } = await env.DB.prepare('SELECT id, name, lat, lng FROM items WHERE trip_id = ?').bind(tripId).all();
    const plan = await planTrip(env, results, exists.days);
    const layout = { 0: [] };
    plan.days.forEach((ids, i) => { layout[i + 1] = ids; });
    const tips = {};
    plan.tips.forEach((t, i) => { if (t) tips[i + 1] = t; });
    await env.DB.batch([
      ...layoutStatements(env, tripId, layout),
      env.DB.prepare('UPDATE trips SET tips = ? WHERE id = ?').bind(JSON.stringify(tips), tripId),
      bump(env, tripId),
    ]);
    return json({ ok: true, usedAi: plan.usedAi });
  }

  return fail('不支援的操作', 404);
}

export default {
  async fetch(request, env) {
    try {
      const res = await handle(request, env);
      if (res) return res;
    } catch (e) {
      console.error(e);
      return fail('系統忙碌,請稍後再試', 500);
    }
    return env.ASSETS.fetch(request);
  },
};
