(function(){
  "use strict";

  const dnt = navigator.doNotTrack === "1" || window.doNotTrack === "1";
  const pageKind = function(){
    const path = location.pathname;
    if(/\/items\/[^/]+\.html$/.test(path)) return {path:"/drugs-data/items/_item", title:"品目別ページ"};
    if(/\/updates\/\d{4}-\d{2}-\d{2}\.html$/.test(path)) return {path:"/drugs-data/updates/_daily", title:"供給変更ページ"};
    if(/\/topics\/[^/]+\.html$/.test(path)) return {path:"/drugs-data/topics/_topic", title:"話題のニュース"};
    if(/\/products\/[^/]+\.html$/.test(path)) return {path:"/drugs-data/products/_product", title:"注目製品ページ"};
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
    "watchlist-activated", "watchlist-import-success", "watchlist-import-failed",
    "watchlist-backup-export", "watchlist-dashboard-open",
    "watchlist-mark-checked", "watchlist-share-success",
    "pwa-install-accepted", "pwa-installed", "app-store-open",
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
  if(new URLSearchParams(location.search).get("src") === "share") window.dsnTrack("share-arrival");
})();
