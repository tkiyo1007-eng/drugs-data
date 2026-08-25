/* 医薬品供給ナビ Web版 Service Worker
 *
 * ねらいは「調剤室・病棟の電波が悪い場所でも開ける」こと。速度のためにデータを
 * 古いまま見せることはしない（供給状況の鮮度が命のサービスなので）。
 *
 * 方針:
 *   - HTMLナビゲーション: ネットワーク優先 → 失敗したらキャッシュ（LPの更新は即反映される）
 *   - 供給データ(CSV/JSON): ネットワーク優先 → 失敗したらキャッシュ（オフライン時のみ前回値）
 *   - manifest: ネットワーク優先（アプリ名・アイコン定義の変更を即反映）
 *   - アイコン・QR: 現在値を即表示しつつ背景再検証
 *
 * キャッシュを作り直したいときは CACHE_VERSION を上げる。
 */
const CACHE_VERSION = "v7";
const SHELL_CACHE = `dsn-shell-${CACHE_VERSION}`;
const DATA_CACHE = `dsn-data-${CACHE_VERSION}`;
const ASSET_CACHE = `dsn-asset-${CACHE_VERSION}`;
const ALL_CACHES = [SHELL_CACHE, DATA_CACHE, ASSET_CACHE];

// オフラインの入り口に必要なファイル。1つでも取得できなければ
// 新しいWorkerをactivateせず、正常な旧キャッシュを維持する。
const REQUIRED_SHELL_FILES = [
  "./",
  "./index.html",
  "./analytics.js",
];

// 補助ページは取得できたものだけ予約する。これらの一時的な失敗で
// 検索画面そのものの更新を妨げない。
const OPTIONAL_SHELL_FILES = [
  "./about.html",
  "./privacy.html",
  "./topics/index.html",
  "./products/index.html",
];

const ASSET_FILES = [
  "./manifest.webmanifest",
  "./icon-192.png",
  "./icon-512.png",
  "./icon-maskable-512.png",
  "./sonamemo-icon.png",
  "./lumical-icon.png",
  "./qr-appstore.svg",
  "./qr-sonamemo.png",
  "./qr-lumical.png",
];

// 供給データ本体（毎日更新されるのでネットワーク優先で扱う）
const DATA_FILES = [
  "drugs_app_ready.csv",
  "version.json",
  "status_changes.json",
  "news.json",
  "maker_announcements.json",
  "announcement_summaries.json",
  "announcement_packages.json",
  "resolution_stats.json",
  "maker_links.json",
  "manual_announcements.json",
  "maker_collection_health.json",
  "product_lifecycle.json",
  "supply_discrepancies.json",
  "featured_products.json",
  "industry_topics.json",
  "items/keys.json",
];

async function migratePreviousDataCache(){
  const cacheNames = await caches.keys();
  const previousDataCaches = cacheNames
    .filter(name => name.startsWith("dsn-data-") && name !== DATA_CACHE)
    .reverse(); // CacheStorage.keys()は作成順。直近版を先に移す。
  if(!previousDataCaches.length) return;

  const target = await caches.open(DATA_CACHE);
  for(const cacheName of previousDataCaches){
    const source = await caches.open(cacheName);
    for(const request of await source.keys()){
      if(await target.match(request)) continue;
      const response = await source.match(request);
      if(response) await target.put(request, response);
    }
  }
}

self.addEventListener("install", event => {
  event.waitUntil((async () => {
    const shell = await caches.open(SHELL_CACHE);
    // addAllはバッチ全体を原子的に追加する。catchしないことで、
    // 必須シェルが欠けた新Workerが旧Workerを置き換えるのを防ぐ。
    await shell.addAll(REQUIRED_SHELL_FILES);

    const assets = await caches.open(ASSET_CACHE);
    await Promise.all([
      ...OPTIONAL_SHELL_FILES.map(file => shell.add(file).catch(() => {})),
      ...ASSET_FILES.map(file => assets.add(file).catch(() => {})),
    ]);

    // 更新直後に圏外に入っても前回の供給データを使えるよう、
    // activateが旧cacheを消す前に新DATA_CACHEへ移す。
    await migratePreviousDataCache();
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", event => {
  event.waitUntil((async () => {
    // install中の移行後に旧Workerの進行中fetchが保存を完了する
    // レースに備え、旧cacheを消す直前にもう一度取り込む。
    await migratePreviousDataCache();
    const keys = await caches.keys();
    await Promise.all(
      keys.filter(key => key.startsWith("dsn-") && !ALL_CACHES.includes(key))
        .map(key => caches.delete(key))
    );
    await self.clients.claim();
  })());
});

// ネットワークが「切れる」のではなく「応答しない」場合の待ち時間の上限。
// 圏外なら fetch はすぐ失敗するが、電波が弱い場所や認証が要るWi-Fiでは応答が
// 返らないまま待たされることがある。そのときは前回のキャッシュを見せる方がよい。
// 遅いだけで生きている回線では最新を取れるよう、短すぎない値にしてある
const NETWORK_TIMEOUT_MS = 8000;

// ネットワーク優先。取得できたらキャッシュを更新する。
// 失敗した場合と、上限時間内に応答がない場合はキャッシュを返す
// ブラウザのHTTPキャッシュを素通りさせず、必ずサーバーに問い合わせる。
// 既定のまま fetch すると HTTP キャッシュが古い内容をそのまま返すことがあり、
// 「ネットワーク優先」と言いながら前日のデータを表示してしまう。
// no-cache は条件付きリクエスト（304が返れば本体は再ダウンロードしない）なので、
// 約1MBのCSVでも通信量はほとんど増えない
function revalidatingFetch(request){
  try{
    return fetch(request, {cache: "no-cache"});
  }catch(e){
    return fetch(request); // 一部の環境で init 付き fetch が使えない場合の保険
  }
}

// キャッシュから返したことをページ側へ伝える。単なるHTTP 200のままだと、
// 最新データと前回値を見分けられず、医薬品情報の鮮度を誤認させてしまう。
function markCachedFallback(response){
  const headers = new Headers(response.headers);
  headers.set("X-DSN-Source", "cache");
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

function networkFirst(request, cacheName, {fallbackOnHttpError=false, event=null}={}){
  const cachePromise = caches.open(cacheName);
  const network = cachePromise.then(async cache => {
    const res = await revalidatingFetch(request);
    if(res && res.ok){
      // 保存完了まで追跡する。put()を待たずにレスポンスだけ返すと、Service Workerが
      // 停止されて次回オフライン時のキャッシュが残っていないことがある
      await cache.put(request, res.clone());
      return res;
    }
    // CSV/JSONは一時的な5xxや配信エラーでも前回値を使えるようにする。
    // ナビゲーションは404をLPへ化けさせないため、HTTPレスポンスをそのまま返す
    return fallbackOnHttpError ? null : res;
  });

  // タイムアウト後にキャッシュを先に返しても、進行中の取得と保存をWorkerの
  // ライフタイムに結び付ける。waitUntilはイベント処理中に同期的に呼ぶ必要がある
  if(event) event.waitUntil(network.then(()=>{}, ()=>{}));

  return (async ()=>{
    const cache = await cachePromise;
    const hit = await cache.match(request);
    if(!hit){
      const res = await network; // キャッシュが無ければネットワークを待つしかない
      if(res) return res;
      throw new Error("Network response was not successful");
    }

    let timer;
    try{
      const res = await Promise.race([
        network.catch(() => null),
        new Promise(resolve => { timer = setTimeout(() => resolve(null), NETWORK_TIMEOUT_MS); }),
      ]);
      // タイムアウトしてキャッシュを返したあとも network は動き続け、
      // 応答が返ればキャッシュを更新するので次回は新しい方が出る
      return res || markCachedFallback(hit);
    }finally{
      clearTimeout(timer);
    }
  })();
}

// キャッシュ優先。無ければ取得してから入れる
async function cacheFirst(request, cacheName){
  const cache = await caches.open(cacheName);
  const hit = await cache.match(request);
  if(hit) return hit;
  const res = await fetch(request);
  if(res && res.ok) cache.put(request, res.clone());
  return res;
}

// 画像はキャッシュを即座に返し、同時に背景で再検証する。
// 同じURLのアイコンやQRを差し替えても、次回表示で新しくなる。
function staleWhileRevalidate(request, cacheName, event){
  const cachePromise = caches.open(cacheName);
  const refresh = cachePromise.then(cache => revalidatingFetch(request).then(async res => {
    if(res && res.ok) await cache.put(request, res.clone());
    return res;
  }));
  // 初回waitUntilはfetchイベントの同期処理中に登録する必要がある。
  // cacheをawaitした後に呼ぶと、ブラウザによってはInvalidStateErrorになる。
  if(event) event.waitUntil(refresh.then(()=>{}, ()=>{}));
  return cachePromise.then(async cache => {
    const hit = await cache.match(request);
    return hit || refresh;
  });
}

self.addEventListener("fetch", event => {
  const req = event.request;
  if(req.method !== "GET") return;

  const url = new URL(req.url);

  // Webフォントは内容が変わらないのでキャッシュ優先。
  // それ以外のクロスオリジン（アクセス解析など）には一切手を出さない
  if(url.origin !== self.location.origin){
    if(url.hostname === "fonts.googleapis.com" || url.hostname === "fonts.gstatic.com"){
      event.respondWith(cacheFirst(req, ASSET_CACHE).catch(() => fetch(req)));
    }
    return;
  }

  // ページ遷移（LP本体・品目別ページ）
  if(req.mode === "navigate"){
    event.respondWith(
      networkFirst(req, SHELL_CACHE, {event}).catch(() => caches.match("./index.html"))
    );
    return;
  }

  // 供給データ
  if(DATA_FILES.some(f => url.pathname.endsWith("/" + f) || url.pathname.endsWith(f))){
    event.respondWith(networkFirst(req, DATA_CACHE, {fallbackOnHttpError:true, event}));
    return;
  }

  // マニフェストは定義変更を即反映。失敗時だけ前回値を使う。
  if(url.pathname.endsWith(".webmanifest")){
    event.respondWith(networkFirst(req, ASSET_CACHE, {fallbackOnHttpError:true, event}));
    return;
  }

  // アイコン・画像・QRは即表示+背景再検証。
  if(/\.(png|svg|ico)$/.test(url.pathname)){
    event.respondWith(staleWhileRevalidate(req, ASSET_CACHE, event).catch(() => fetch(req)));
    return;
  }
});
