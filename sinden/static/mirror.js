// 「ことばを確かめる」を押して、AI の返事を待つあいだ、鏡に映している様子を出す
(() => {
  const form = document.getElementById("plea-form");
  const waiting = document.querySelector("[data-mirror-waiting]");
  if (!form || !waiting) return;
  form.addEventListener("submit", (e) => {
    const button = e.submitter;
    if (!button || !button.hasAttribute("data-reflect")) return;
    waiting.hidden = false;
    waiting.scrollIntoView({ block: "center", behavior: "smooth" });
    // 送信が始まったあとに、ボタンを押せなくする（二重押しを防ぐ）
    setTimeout(() => {
      form.querySelectorAll("button").forEach((b) => { b.disabled = true; });
    }, 0);
  });
})();
