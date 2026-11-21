// 誘いを、本人が LINE などで相手に送る（スマホの共有機能。なければリンクをコピー）
(() => {
  const btn = document.querySelector("[data-share]");
  if (!btn) return;
  const note = document.querySelector("[data-share-note]");
  const say = (msg) => {
    if (!note) return;
    note.textContent = msg;
    note.hidden = false;
  };
  btn.addEventListener("click", async () => {
    const url = location.origin + "/";
    const data = { title: btn.dataset.title, text: btn.dataset.text, url };
    try {
      if (navigator.share) {
        await navigator.share(data);
        return;
      }
      await navigator.clipboard.writeText(`${data.text}\n${url}`);
      say("コピーしました。LINE などに貼って、相手に送ってください。");
    } catch (e) {
      if (e && e.name === "AbortError") return; // 本人がやめた
      say(`うまく送れませんでした。このリンクを、相手に伝えてください：${url}`);
    }
  });
})();
