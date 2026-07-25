/* 医薬品供給ナビ Web版 Service Worker
 *
 * ねらいは「調剤室・病棟の電波が悪い場所でも開ける」こと。速度のためにデータを
 * 古いまま見せることはしない（供給状況の鮮度が命のサービスなので）。
 *
 * 方針:
 *   - HTMLナビゲーション: ネットワーク優先 → 失敗したらキャッシュ（LPの更新は即反映される）
 *   - 供給データ(CSV/JSON): ネットワーク優先 → 失敗したらキャッシュ（オフライン時のみ前回値）
 *   - 静的アセット(アイコン・Webフォント): キャッシュ優先（内容が変わらないもの）
 *
 * キャッシュを作り直したいときは CACHE_VERSION を上げる。
 */
const CACHE_VERSION = "v1";
const SHELL_CACHE = `dsn-shell-${CACHE_VERSION}`;
const DATA_CACHE = `dsn-data-${CACHE_VERSION}`;
const ASSET_CACHE = `dsn-asset-${CACHE_VERSION}`;
const ALL_CACHES = [SHELL_CACHE, DATA_CACHE, ASSET_CACHE];

// オフラインでも最低限開くために先読みするファイル
const SHELL_FILES = ["./", "./index.html", "./privacy.html", "./manifest.webmanifest", "./icon-192.png"];

// 供給データ本体（毎日更新されるのでネットワーク優先で扱う）
const DATA_FILES = [
  "drugs_app_ready.csv",
  "version.json",
  "status_changes.json",
  "news.json",
  "crisis_index.json",
];

self.addEventListener("install", event => {
  event.waitUntil(
    // 1ファイルでも取れないと addAll 全体が失敗するため個別に入れる
    caches.open(SHELL_CACHE)
      .then(c => Promise.all(SHELL_FILES.map(f => c.add(f).catch(() => {}))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(
        keys.filter(k => k.startsWith("dsn-") && !ALL_CACHES.includes(k))
            .map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
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

async function networkFirst(request, cacheName){
  const cache = await caches.open(cacheName);
  const network = revalidatingFetch(request).then(res => {
    if(res && res.ok) cache.put(request, res.clone());
    return res;
  });
  network.catch(() => {}); // 下の race とは別に握りつぶし、未処理の拒否にしない

  const hit = await cache.match(request);
  if(!hit) return network; // キャッシュが無ければネットワークを待つしかない

  let timer;
  try{
    const res = await Promise.race([
      network.catch(() => null),
      new Promise(resolve => { timer = setTimeout(() => resolve(null), NETWORK_TIMEOUT_MS); }),
    ]);
    // タイムアウトしてキャッシュを返したあとも network は動き続け、
    // 応答が返ればキャッシュを更新するので次回は新しい方が出る
    return res || hit;
  }finally{
    clearTimeout(timer);
  }
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
      networkFirst(req, SHELL_CACHE).catch(() => caches.match("./index.html"))
    );
    return;
  }

  // 供給データ
  if(DATA_FILES.some(f => url.pathname.endsWith("/" + f) || url.pathname.endsWith(f))){
    event.respondWith(networkFirst(req, DATA_CACHE));
    return;
  }

  // アイコン・画像・マニフェスト
  if(/\.(png|svg|webmanifest|ico)$/.test(url.pathname)){
    event.respondWith(cacheFirst(req, ASSET_CACHE).catch(() => fetch(req)));
    return;
  }
});
