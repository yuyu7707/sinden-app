// 女神の灯が揺れる確認の画面：表示されたら、灯と文が見える位置までスクロールする
(() => {
  const el = document.querySelector(".sensor");
  if (!el) return;
  el.scrollIntoView({ block: "start", behavior: "smooth" });
})();
