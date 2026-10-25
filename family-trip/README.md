# 家人旅行規劃

給家中長輩用的簡單旅遊規劃網頁:把 Google 地圖的分享連結貼進來,AI 幫忙分天排順序,家人(約 5 人)可同時編輯。

跑在 Cloudflare 上:Workers(API + 靜態頁)、D1(資料庫)、Workers AI(排行程)。不需要 Google API。

## 怎麼用

1. 首頁輸入旅行名稱和天數,按「開始規劃」。
2. 在 Google 地圖按「分享」複製連結,貼到「加入地點」(也可以直接打地點名稱)。
3. 按「AI 幫我排行程」,AI 會依距離分天排序;之後可用 ↑ ↓ 與「移到第幾天」手動調整。
4. 按「分享給家人」,把網址傳到 LINE。**知道網址的人都能編輯**,網址本身就是通行證(12 碼隨機字元),請不要公開張貼。

## 部署

需要 Node 20 以上與 Cloudflare 帳號。

```sh
cd family-trip
npm install
npx wrangler login
npx wrangler d1 create family-trip-db      # 把印出的 database_id 貼進 wrangler.jsonc
npm run db:init                            # 建立資料表(遠端)
npm run deploy
```

部署完會得到 `https://family-trip.<你的帳號>.workers.dev`。

## 本機開發

```sh
npm run db:init:local
npm run dev        # Workers AI 綁定走遠端,需要 wrangler login
npm test
```

沒登入時 `wrangler dev` 無法啟動 AI 綁定;要只測 API,可以暫時從 `wrangler.jsonc` 拿掉 `ai` 區塊,此時「AI 幫我排行程」會自動改用依距離排序的保底方案。

## 模型與費用

預設模型在 `wrangler.jsonc` 的 `AI_MODEL`(目前是 `@cf/google/gemma-4-26b-a4b-it`)。Workers AI 每天有 10,000 neurons 免費額度,一次排程約幾十 neurons,五個人用不完。Workers、D1 在免費額度內也是 $0。模型清單和價格以 Cloudflare 官方文件為準,若模型下架,改這個變數即可。

AI 輸出一律驗證:未知或重複的地點會被丟掉、漏掉的會補回;AI 失敗或逾時則改用依距離排序。

## 已知限制

- Google 短網址若被導向同意頁或需登入的頁面,會讀不到名稱,畫面會請使用者改打地點名稱。
- 沒有帳號系統;連結外流就等於開放編輯。需要更嚴格可再加 Cloudflare Access。
- 同時編輯採「最後寫入為準」,每 4 秒同步一次。
- 尚未實作:翻譯、機票與飯店卡片。
