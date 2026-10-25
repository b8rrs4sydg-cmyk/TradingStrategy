// AI 排行程:把地點分配到各天並排序。AI 輸出一律驗證,失敗就用幾何方法保底。

const SYSTEM = `你是台灣旅遊行程規劃助手,使用者是家中長輩,請用簡單的繁體中文。
任務:把給定的地點分配到指定天數,同一天的地點要地理上相近,並排成順暢的參觀順序(考慮路線不要來回折返、午餐時間、景點開放時段常識)。
規則:
- 每個地點 id 必須剛好出現一次,不可新增或遺漏。
- 每天地點數量盡量平均,長輩體力有限,每天不要排太滿。
- tips 是每天一句簡短提醒(如:早點出發、這天走路較多、記得預約)。
只輸出 JSON。`;

const SCHEMA = {
  type: 'object',
  properties: {
    days: { type: 'array', items: { type: 'array', items: { type: 'string' } } },
    tips: { type: 'array', items: { type: 'string' } },
  },
  required: ['days', 'tips'],
};

const dist = (a, b) => Math.hypot(a.lat - b.lat, (a.lng - b.lng) * Math.cos((a.lat * Math.PI) / 180));

// 保底:最近鄰路線,再平均切成 N 天。沒有座標的放最後。
export function fallbackPlan(items, nDays) {
  const withGeo = items.filter((i) => i.lat != null && i.lng != null);
  const noGeo = items.filter((i) => i.lat == null || i.lng == null);
  const route = [];
  const left = [...withGeo];
  if (left.length) {
    let cur = left.splice(left.reduce((b, it, i, a) => (it.lng < a[b].lng ? i : b), 0), 1)[0];
    route.push(cur);
    while (left.length) {
      let bi = 0;
      for (let i = 1; i < left.length; i++) if (dist(cur, left[i]) < dist(cur, left[bi])) bi = i;
      cur = left.splice(bi, 1)[0];
      route.push(cur);
    }
  }
  const all = [...route, ...noGeo];
  const days = Array.from({ length: nDays }, () => []);
  const per = Math.ceil(all.length / nDays) || 1;
  all.forEach((it, i) => days[Math.min(Math.floor(i / per), nDays - 1)].push(it.id));
  return { days, tips: [] };
}

// 驗證並修正 AI 輸出:去掉未知/重複 id,補上遺漏的,補滿天數。
export function normalizePlan(raw, items, nDays) {
  const valid = new Set(items.map((i) => i.id));
  const seen = new Set();
  const days = Array.from({ length: nDays }, () => []);
  const src = Array.isArray(raw?.days) ? raw.days : [];
  src.slice(0, nDays).forEach((d, di) => {
    if (!Array.isArray(d)) return;
    for (const id of d) {
      if (typeof id === 'string' && valid.has(id) && !seen.has(id)) { seen.add(id); days[di].push(id); }
    }
  });
  const missing = items.filter((i) => !seen.has(i.id));
  // 遺漏的放到目前最少的那天
  for (const it of missing) days.reduce((m, d) => (d.length < m.length ? d : m), days[0]).push(it.id);
  const tips = Array.isArray(raw?.tips) ? raw.tips.slice(0, nDays).map((t) => String(t ?? '').slice(0, 80)) : [];
  return { days, tips };
}

export function parseAiResponse(result) {
  const r = result?.response ?? result;
  if (r && typeof r === 'object') return r;
  if (typeof r !== 'string') return null;
  const m = r.match(/\{[\s\S]*\}/);
  if (!m) return null;
  try { return JSON.parse(m[0]); } catch { return null; }
}

export async function planTrip(env, items, nDays) {
  if (!items.length) return { days: Array.from({ length: nDays }, () => []), tips: [], usedAi: false };
  const list = items.map((i) => ({
    id: i.id, name: i.name,
    lat: i.lat != null ? +i.lat.toFixed(4) : undefined,
    lng: i.lng != null ? +i.lng.toFixed(4) : undefined,
  }));
  try {
    const result = await env.AI.run(env.AI_MODEL, {
      messages: [
        { role: 'system', content: SYSTEM },
        { role: 'user', content: `天數:${nDays}\n地點:${JSON.stringify(list)}\n請輸出 {"days":[[id,...],...共${nDays}天],"tips":[每天一句提醒,共${nDays}句]}` },
      ],
      response_format: { type: 'json_schema', json_schema: SCHEMA },
      max_tokens: 1500,
    });
    const raw = parseAiResponse(result);
    if (raw) return { ...normalizePlan(raw, items, nDays), usedAi: true };
  } catch (e) {
    console.error('AI plan failed', e);
  }
  return { ...fallbackPlan(items, nDays), usedAi: false };
}
