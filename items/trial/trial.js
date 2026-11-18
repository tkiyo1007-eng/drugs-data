(() => {
  const panel = document.querySelector(".summary");
  if (!panel) return;
  const button = document.getElementById("share");
  const feedback = document.getElementById("feedback");
  const manual = document.getElementById("manualCopy");
  const freshness = document.getElementById("freshness");
  const date = panel.dataset.source;
  const product = document.querySelector("h1").textContent;
  const status = Array.from(panel.querySelectorAll(".status, .caution"), el => el.textContent).join(" / ");
  const spec = document.querySelector(".spec").firstChild.textContent.trim();
  const url = new URL(location.pathname, location.origin).href;
  let matches = false;
  function dateIsRecent() {
    const age = Date.now() - Date.parse(date + "T00:00:00+09:00");
    return age >= 0 && age < 7 * 86400000;
  }
  async function checkVersion() {
    matches = false;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch("../../version.json", {cache:"no-cache", signal:controller.signal});
      if (!response.ok || response.headers.get("X-DSN-Source") === "cache") throw new Error();
      const latest = await response.json();
      const validDates = /^\d{4}-\d{2}-\d{2}$/.test(date) && date <= panel.dataset.imported;
      matches = validDates && latest.mhlw_excel_date === date
        && /^[0-9]{8,14}$/.test(panel.dataset.version) && String(latest.version) === panel.dataset.version
        && panel.dataset.version.startsWith(panel.dataset.imported.replaceAll("-", ""))
        && dateIsRecent();
    } catch {
      matches = false;
    } finally {
      clearTimeout(timer);
      freshness.hidden = matches;
      freshness.classList.toggle("warning", !matches);
      freshness.textContent = matches ? "" : "最新データとの一致を確認できません。厚労省の公表ページをご確認ください。";
    }
  }
  checkVersion();
  window.addEventListener("pageshow", event => {
    if (event.persisted) checkVersion();
  });
  button.hidden = false;
  button.addEventListener("click", async () => {
    const text = matches && dateIsRecent()
      ? [product, spec, "厚労省公表 " + status, "厚労省基準日 " + date].join("\n")
      : [product, spec, "最新の供給状況は原典をご確認ください。"].join("\n");
    manual.hidden = true;
    feedback.textContent = "";
    try {
      if (navigator.share) {
        await navigator.share({title:product, text, url});
        feedback.textContent = "共有しました。";
      } else {
        await navigator.clipboard.writeText(text + "\n" + url);
        feedback.textContent = "共有文とリンクをコピーしました。";
      }
    } catch (error) {
      if (error.name === "AbortError") return;
      manual.value = text + "\n" + url;
      manual.hidden = false;
      manual.focus();
      manual.select();
      feedback.textContent = "共有文を選択しました。コピーしてお使いください。";
    }
  });
})();
