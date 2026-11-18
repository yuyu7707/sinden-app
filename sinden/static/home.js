// ホーム：相手がペアに加わった・祠に誘われた・誘いが取り消されたら、画面を新しくする
// （祠に入るのは、本人が「応じる」を押したときだけ）
(() => {
  const home = document.querySelector("[data-home-state]");
  if (!home) return;
  const stateUrl = home.dataset.homeState;
  const version = home.dataset.version;

  setInterval(async () => {
    if (document.hidden) return; // 見ていない間は確かめない
    try {
      const res = await fetch(stateUrl, { headers: { Accept: "application/json" } });
      if (!res.ok) return;
      const data = await res.json();
      if (data.version !== version) location.reload();
    } catch {
      // 通信が切れても、次の回で取り直す
    }
  }, 5000);
})();
