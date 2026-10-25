// Google Maps 連結解析:短網址展開 → 地點名稱 + 座標。不需要 Google API。

const ALLOWED = [
  /^maps\.app\.goo\.gl$/,
  /^goo\.gl$/,
  /^(www\.)?google\.[a-z.]+$/,
  /^maps\.google\.[a-z.]+$/,
  /^consent\.google\.[a-z.]+$/,
];
const isAllowedHost = (h) => ALLOWED.some((re) => re.test(h));

export function extractUrl(text) {
  const m = String(text).match(/https?:\/\/[^\s<>"']+/i);
  if (!m) return { url: null, hint: String(text).trim() };
  const hint = String(text).replace(m[0], '').replace(/\s+/g, ' ').trim();
  return { url: m[0], hint };
}

// 手動追蹤重新導向,每一跳都檢查網域白名單(避免被拿來打任意網址)。
export async function resolveUrl(url, fetchFn = fetch) {
  let cur = url;
  for (let i = 0; i < 6; i++) {
    const u = new URL(cur);
    if (u.protocol !== 'https:' && u.protocol !== 'http:') throw new Error('bad protocol');
    if (!isAllowedHost(u.hostname)) throw new Error('不是 Google 地圖連結');
    if (/^consent\.google\./.test(u.hostname)) {
      const c = u.searchParams.get('continue');
      if (c) { cur = c; continue; }
    }
    // 長網址本身已含資訊,不必再抓
    if (/\/maps\/(place|search|dir)\b/.test(u.pathname) || u.searchParams.has('q')) return cur;
    const res = await fetchFn(cur, {
      redirect: 'manual',
      headers: { 'user-agent': 'Mozilla/5.0 (compatible; FamilyTrip/1.0)' },
    });
    const loc = res.headers.get('location');
    if (loc && res.status >= 300 && res.status < 400) { cur = new URL(loc, cur).toString(); continue; }
    return cur;
  }
  return cur;
}

const dec = (s) => {
  try { return decodeURIComponent(s.replace(/\+/g, ' ')); } catch { return s; }
};
const isCoord = (s) => /^-?\d+(\.\d+)?,\s*-?\d+(\.\d+)?$/.test(s);

export function parseMapsUrl(finalUrl) {
  const u = new URL(finalUrl);
  const full = u.pathname + u.search;
  let name = null, lat = null, lng = null;

  const place = u.pathname.match(/\/maps\/place\/([^/]+)/);
  if (place) name = dec(place[1]);
  if (!name) {
    const q = u.searchParams.get('q') || u.searchParams.get('query');
    if (q && !isCoord(q)) name = q;
  }

  // !3d緯度!4d經度 是地點本身;@緯度,經度 只是地圖視角中心,次選
  const pin = (u.pathname + decodeURIComponent(u.hash || '')).match(/!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)/)
    || full.match(/!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)/);
  const view = full.match(/@(-?\d+\.\d+),(-?\d+\.\d+)/);
  const q = u.searchParams.get('q') || u.searchParams.get('query') || u.searchParams.get('ll');
  const m = pin || (q && isCoord(q) && q.match(/(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)/)) || view;
  if (m) { lat = parseFloat(m[1]); lng = parseFloat(m[2]); }

  if (name && isCoord(name)) name = null;
  return { name, lat, lng };
}

export async function importPlace(text, fetchFn = fetch) {
  const { url, hint } = extractUrl(text);
  if (!url) return { name: hint.slice(0, 80) || null, lat: null, lng: null, url: null };
  const finalUrl = await resolveUrl(url, fetchFn);
  const p = parseMapsUrl(finalUrl);
  return {
    name: (p.name || hint || '').slice(0, 80) || null,
    lat: p.lat,
    lng: p.lng,
    url, // 保留使用者貼的原始連結,點開就是 Google 地圖
  };
}
