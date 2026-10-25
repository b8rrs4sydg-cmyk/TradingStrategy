import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fallbackPlan, normalizePlan, parseAiResponse, planTrip } from '../src/plan.js';

const items = [
  { id: 'a', name: 'A', lat: 35.0, lng: 135.0 },
  { id: 'b', name: 'B', lat: 35.01, lng: 135.01 },
  { id: 'c', name: 'C', lat: 35.7, lng: 139.7 },
  { id: 'd', name: 'D', lat: 35.71, lng: 139.71 },
  { id: 'e', name: 'E', lat: null, lng: null },
];
const allIds = (days) => days.flat().sort().join('');

test('fallbackPlan 每個地點剛好一次,附近的排在一起', () => {
  const { days } = fallbackPlan(items, 2);
  assert.equal(days.length, 2);
  assert.equal(allIds(days), 'abcde');
  const near = (x, y) => days.some((d) => d.includes(x) && d.includes(y));
  assert.ok(near('a', 'b') && near('c', 'd'));
});

test('normalizePlan 移除未知與重複 id、補上遺漏、補滿天數', () => {
  const raw = { days: [['a', 'zzz', 'a'], 'oops'], tips: ['早點出發', 5] };
  const { days, tips } = normalizePlan(raw, items, 3);
  assert.equal(days.length, 3);
  assert.equal(allIds(days), 'abcde');
  assert.equal(tips[0], '早點出發');
});

test('parseAiResponse 支援物件、字串、OpenAI 格式與夾雜文字', () => {
  assert.deepEqual(parseAiResponse({ response: { days: [] } }), { days: [] });
  assert.deepEqual(parseAiResponse({ response: '好的:{"days":[["a"]]} 完成' }), { days: [['a']] });
  assert.deepEqual(parseAiResponse({ choices: [{ message: { content: '{"days":[]}' } }] }), { days: [] });
  assert.equal(parseAiResponse({ response: 'no json' }), null);
});

test('planTrip:AI 回傳亂資料也能得到完整排程', async () => {
  const env = { AI_MODEL: 'm', AI: { run: async () => ({ response: { days: [['a', 'a', 'x']], tips: [] } }) } };
  const r = await planTrip(env, items, 2);
  assert.equal(r.usedAi, true);
  assert.equal(allIds(r.days), 'abcde');
});

test('planTrip:AI 全部失敗就用幾何保底;第一次失敗會重試不帶 schema', async () => {
  let calls = 0;
  const failing = { AI_MODEL: 'm', AI: { run: async () => { calls++; throw new Error('boom'); } } };
  const r = await planTrip(failing, items, 2);
  assert.equal(r.usedAi, false);
  assert.equal(allIds(r.days), 'abcde');
  assert.equal(calls, 2);

  const seen = [];
  const retry = { AI_MODEL: 'm', AI: { run: async (_m, o) => {
    seen.push(!!o.response_format);
    if (o.response_format) throw new Error('unsupported');
    return { response: '{"days":[["a","b"],["c","d","e"]],"tips":["x","y"]}' };
  } } };
  const r2 = await planTrip(retry, items, 2);
  assert.deepEqual(seen, [true, false]);
  assert.equal(r2.usedAi, true);
});

test('planTrip 沒有地點時不呼叫 AI', async () => {
  const env = { AI: { run: () => { throw new Error('no'); } } };
  const r = await planTrip(env, [], 3);
  assert.deepEqual(r.days, [[], [], []]);
});
