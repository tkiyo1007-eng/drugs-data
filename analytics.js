(function(){
  "use strict";

  const dnt = navigator.doNotTrack === "1" || window.doNotTrack === "1";
  const pageKind = function(){
    const path = location.pathname;
    if(path.endsWith("/items/") || path.endsWith("/items/index.html")) return {path:"/drugs-data/items/", title:"品目別一覧"};
    if(path.endsWith("/items/limited.html")) return {path:"/drugs-data/items/limited", title:"限定出荷一覧"};
    if(path.endsWith("/items/stopped.html")) return {path:"/drugs-data/items/stopped", title:"供給停止一覧"};
    if(path.endsWith("/items/supplemental.html")) return {path:"/drugs-data/items/supplemental", title:"販売中止・メーカー補足一覧"};
    if(path.endsWith("/items/resumed.html")) return {path:"/drugs-data/items/resumed", title:"通常出荷へ回復した品目一覧"};
    if(/\/items\/[^/]+\.html$/.test(path)) return {path:"/drugs-data/items/_item", title:"品目別ページ"};
    if(/\/updates\/\d{4}-\d{2}-\d{2}\.html$/.test(path)) return {path:"/drugs-data/updates/_daily", title:"供給変更ページ"};
    if(/\/topics\/[^/]+\.html$/.test(path)) return {path:"/drugs-data/topics/_topic", title:"話題のニュース"};
    if(/\/products\/[^/]+\.html$/.test(path)) return {path:"/drugs-data/products/_product", title:"注目製品ページ"};
    if(/\/guides\/[^/]+\.html$/.test(path)) return {path:"/drugs-data/guides/_guide", title:"供給情報の確認ガイド"};
    return {path:path || "/drugs-data/", title:document.title || "医薬品供給ナビ"};
  };
  const referrerOrigin = function(){
    if(!document.referrer) return "";
    try{ return new URL(document.referrer).origin; }
    catch(e){ return ""; }
  };
  const existing = window.goatcounter || {};
  window.goatcounter = Object.assign(existing, {
    no_events: true,
    no_onload: dnt,
    path: function(){ return pageKind().path; },
    title: function(){ return pageKind().title; },
    referrer: referrerOrigin,
  });

  const allowed = new Set([
    "search-success", "search-zero", "detail-open", "detail-share-success", "share-arrival",
    "data-load-failed", "daily-share-success", "feed-url-copy",
    "watchlist-first-add", "watchlist-activated", "watchlist-import-success", "watchlist-import-failed",
    "watchlist-backup-export", "watchlist-dashboard-open",
    "watchlist-mark-checked", "watchlist-share-success",
    "pwa-install-accepted", "pwa-installed", "app-store-open",
    "item-web-open", "item-share-success", "item-app-store-open",
    "search-cta-open", "official-source-open", "related-item-open", "topic-to-search",
    "static-page-share-success",
  ]);
  const queue = [];
  window.dsnTrack = function(name){
    if(dnt || !allowed.has(name)) return false;
    if(window.goatcounter && typeof window.goatcounter.count === "function"){
      window.goatcounter.count({path:"event:"+name, title:name, event:true});
    }else if(queue.length < 50){
      queue.push(name);
    }
    return true;
  };
  function flush(){
    if(!window.goatcounter || typeof window.goatcounter.count !== "function") return;
    while(queue.length){
      const name = queue.shift();
      window.goatcounter.count({path:"event:"+name, title:name, event:true});
    }
  }
  window.addEventListener("load", function(){ setTimeout(flush, 0); });
  document.addEventListener("click", function(event){
    const target = event.target && event.target.closest ? event.target.closest("[data-dsn-event]") : null;
    if(target && target.dataset) window.dsnTrack(target.dataset.dsnEvent);
  });
  document.addEventListener("click", async function(event){
    const button = event.target && event.target.closest
      ? event.target.closest("[data-dsn-share-page]") : null;
    if(!button) return;
    const container = button.closest(".page-share");
    const status = container ? container.querySelector(".page-share-status") : null;
    const url = new URL(location.href);
    url.hash = "";
    url.searchParams.set("src", "share");
    try{
      if(navigator.share){
        await navigator.share({title:document.title, url:url.href});
        if(status) status.textContent = "共有しました。";
      }else{
        await navigator.clipboard.writeText(url.href);
        if(status) status.textContent = "共有用リンクをコピーしました。";
      }
      window.dsnTrack("static-page-share-success");
    }catch(error){
      if(error && error.name === "AbortError") return;
      if(status) status.textContent = "共有できませんでした。URL欄からリンクをコピーしてください。";
    }
  });
  if(new URLSearchParams(location.search).get("src") === "share") window.dsnTrack("share-arrival");
})();
