import { test } from 'node:test';
import assert from 'node:assert/strict';
import { extractUrl, parseMapsUrl, resolveUrl, importPlace } from '../src/maps.js';

test('extractUrl 分離分享文字中的名稱與連結', () => {
  const r = extractUrl('淺草寺\nhttps://maps.app.goo.gl/AbC123');
  assert.equal(r.url, 'https://maps.app.goo.gl/AbC123');
  assert.equal(r.hint, '淺草寺');
  assert.equal(extractUrl('東京鐵塔').url, null);
});

test('parseMapsUrl 取地點名稱與釘選座標(優先 !3d!4d)', () => {
  const u = 'https://www.google.com/maps/place/%E6%B7%BA%E8%8D%89%E5%AF%BA/@35.7147,139.7967,17z/data=!3m1!4b1!4m6!3m5!1s0x0:0x1!8m2!3d35.7148374!4d139.7967029';
  const r = parseMapsUrl(u);
  assert.equal(r.name, '淺草寺');
  assert.equal(r.lat, 35.7148374);
  assert.equal(r.lng, 139.7967029);
});

test('parseMapsUrl 名稱中的 + 轉空白,只有 @ 時用視角座標', () => {
  const r = parseMapsUrl('https://www.google.com/maps/place/Tokyo+Skytree/@35.71,139.81,15z');
  assert.equal(r.name, 'Tokyo Skytree');
  assert.equal(r.lat, 35.71);
});

test('parseMapsUrl 支援 ?q= 名稱與 ?q=緯度,經度', () => {
  assert.equal(parseMapsUrl('https://www.google.com/maps?q=Shibuya+Crossing').name, 'Shibuya Crossing');
  const c = parseMapsUrl('https://maps.google.com/?q=35.6595,139.7005');
  assert.equal(c.name, null);
  assert.equal(c.lat, 35.6595);
});

test('resolveUrl 展開短網址,並逐跳檢查網域', async () => {
  const calls = [];
  const fetchFn = async (u) => {
    calls.push(u);
    if (u.startsWith('https://maps.app.goo.gl/')) {
      return new Response(null, { status: 302, headers: { location: 'https://www.google.com/maps/place/A/@1,2,3z' } });
    }
    throw new Error('should not fetch long url');
  };
  const out = await resolveUrl('https://maps.app.goo.gl/x', fetchFn);
  assert.equal(out, 'https://www.google.com/maps/place/A/@1,2,3z');
  assert.equal(calls.length, 1);
});

test('resolveUrl 拒絕非 Google 網域(含轉址到外部)', async () => {
  await assert.rejects(resolveUrl('https://evil.example.com/x', async () => new Response()));
  const redirectOut = async () => new Response(null, { status: 302, headers: { location: 'http://169.254.169.254/' } });
  await assert.rejects(resolveUrl('https://maps.app.goo.gl/x', redirectOut));
});

test('resolveUrl 處理 consent 頁面的 continue 參數', async () => {
  const out = await resolveUrl(
    'https://consent.google.com/ml?continue=' + encodeURIComponent('https://www.google.com/maps/place/B/@1,2,3z'),
    async () => { throw new Error('no fetch'); });
  assert.equal(out, 'https://www.google.com/maps/place/B/@1,2,3z');
});

test('importPlace:純文字直接當名稱;連結失敗時用分享文字的名稱', async () => {
  assert.deepEqual(await importPlace('清水寺'), { name: '清水寺', lat: null, lng: null, url: null });
  const r = await importPlace('一蘭拉麵 https://www.google.com/maps?q=35.6,139.7');
  assert.equal(r.lat, 35.6);
  assert.equal(r.name, '一蘭拉麵');
  assert.match(r.url, /^https:\/\/www\.google\.com/);
});
