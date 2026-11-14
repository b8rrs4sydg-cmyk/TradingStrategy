"""Can the page (a browser) and the crawler (python) talk peer to peer, with no tunnel?

``answer``  runs on one runner: aiortc waits for an offer on an ntfy topic, answers it and echoes data-channel messages.
``browser`` runs on another runner: a real Chromium on the published page's origin offers, then pings over the channel.
ntfy only carries the two SDP messages (signalling); the lookup data would flow over the data channel.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
import urllib.request

NTFY = "https://ntfy.sh"
STUN = "stun:stun.l.google.com:19302"


def post(topic: str, text: str) -> None:
    urllib.request.urlopen(
        urllib.request.Request(f"{NTFY}/{topic}", data=text.encode(), method="POST"), timeout=15
    ).read()


def poll(topic: str, since: str = "10m") -> list[dict]:
    with urllib.request.urlopen(f"{NTFY}/{topic}/json?poll=1&since={since}", timeout=20) as r:
        return [json.loads(line) for line in r.read().decode().splitlines() if line.strip()]


async def answer(topic: str) -> int:
    from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription

    deadline = time.time() + 240
    offer = None
    while time.time() < deadline and offer is None:
        for ev in poll(topic):
            try:
                m = json.loads(ev.get("message", ""))
            except ValueError:
                continue
            if m.get("type") == "offer":
                offer = m
        if offer is None:
            await asyncio.sleep(2)
    if offer is None:
        print("no offer received")
        return 1
    print("offer received", flush=True)
    pc = RTCPeerConnection(RTCConfiguration([RTCIceServer(urls=[STUN])]))
    done = asyncio.Event()

    @pc.on("datachannel")
    def on_channel(ch):
        print("data channel", ch.label, flush=True)

        @ch.on("message")
        def on_message(msg):
            print("got", msg, flush=True)
            ch.send("pong:" + str(msg))
            done.set()

    await pc.setRemoteDescription(RTCSessionDescription(sdp=offer["sdp"], type="offer"))
    await pc.setLocalDescription(await pc.createAnswer())
    post(topic, json.dumps({"type": "answer", "sdp": pc.localDescription.sdp}))
    print("answer posted", flush=True)
    try:
        await asyncio.wait_for(done.wait(), timeout=90)
        await asyncio.sleep(3)
        print("ANSWERER OK")
        return 0
    except TimeoutError:
        print("ANSWERER: no message over the channel; ice=", pc.iceConnectionState)
        return 1
    finally:
        await pc.close()


JS = """
async ({topic, stun}) => {
  const out = [];
  const t0 = performance.now();
  const mark = s => out.push(((performance.now() - t0) / 1000).toFixed(1) + 's ' + s);
  const pc = new RTCPeerConnection({ iceServers: [{ urls: stun }] });
  const dc = pc.createDataChannel('lookup');
  const opened = new Promise(res => { dc.onopen = () => { mark('channel open'); res(true); }; });
  const reply = new Promise(res => { dc.onmessage = e => { mark('got ' + e.data); res(e.data); }; });
  pc.oniceconnectionstatechange = () => mark('ice ' + pc.iceConnectionState);
  await pc.setLocalDescription(await pc.createOffer());
  await new Promise(res => {
    if (pc.iceGatheringState === 'complete') return res();
    pc.onicegatheringstatechange = () => pc.iceGatheringState === 'complete' && res();
    setTimeout(res, 8000);
  });
  mark('offer ready, candidates: ' + (pc.localDescription.sdp.match(/a=candidate/g) || []).length);
  await fetch('https://ntfy.sh/' + topic, { method: 'POST', body: JSON.stringify({ type: 'offer', sdp: pc.localDescription.sdp }) });
  mark('offer posted');
  let answer = null;
  for (let i = 0; i < 60 && !answer; i++) {
    const r = await fetch('https://ntfy.sh/' + topic + '/json?poll=1&since=10m');
    for (const line of (await r.text()).split('\\n')) {
      if (!line.trim()) continue;
      try { const m = JSON.parse(JSON.parse(line).message || 'null'); if (m && m.type === 'answer') answer = m; } catch {}
    }
    if (!answer) await new Promise(res => setTimeout(res, 2000));
  }
  if (!answer) { mark('no answer'); return { ok: false, out }; }
  mark('answer received');
  await pc.setRemoteDescription({ type: 'answer', sdp: answer.sdp });
  const ok = await Promise.race([opened, new Promise(res => setTimeout(() => res(false), 30000))]);
  if (!ok) { mark('channel did not open'); return { ok: false, out }; }
  dc.send('ping');
  const got = await Promise.race([reply, new Promise(res => setTimeout(() => res(null), 15000))]);
  return { ok: got === 'pong:ping', got, out };
}
"""


async def browser(topic: str, url: str) -> int:
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        page = await b.new_page()
        await page.goto(url, wait_until="load")
        res = await asyncio.wait_for(page.evaluate(JS, {"topic": topic, "stun": STUN}), timeout=200)
        for line in res["out"]:
            print(" ", line)
        print("BROWSER", "OK" if res["ok"] else "FAILED", res.get("got"))
        await b.close()
        return 0 if res["ok"] else 1


if __name__ == "__main__":
    mode, topic = sys.argv[1], sys.argv[2]
    if mode == "answer":
        sys.exit(asyncio.run(answer(topic)))
    sys.exit(
        asyncio.run(
            browser(
                topic,
                sys.argv[3]
                if len(sys.argv) > 3
                else "https://b8rrs4sydg-cmyk.github.io/TradingStrategy/",
            )
        )
    )
