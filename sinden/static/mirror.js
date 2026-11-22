// 鏡と本の中の文字を、はみ出さない大きさにそろえる。
// 「ことばを確かめる」を押して AI の返事を待つあいだ、すぐに、鏡の映像を出す
(() => {
  // 1) 文字が、鏡・本のページからはみ出すときは、文字を少しずつ小さくする（下限あり）
  const fit = (box) => {
    box.style.fontSize = "";
    let size = parseFloat(getComputedStyle(box).fontSize);
    const min = 14;
    // 飾り（霧や光）の大きさは数えず、文字そのものの高さで測る。浮き出る動き（拡大）の途中でも、本来の大きさで測れるよう、offsetHeight を使う
    const text = box.querySelector(".mirror-text, .lamp-text") || box;
    while (text.offsetHeight > box.clientHeight + 1 && size > min) {
      size -= 0.5;
      box.style.fontSize = size + "px";
    }
  };
  const fitAll = () => document.querySelectorAll(".fit-box").forEach((box) => {
    if (box.closest("[hidden]")) return;
    fit(box);
  });
  fitAll();
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(fitAll);
  window.addEventListener("resize", fitAll);

  // 2) ボタンを押したら、すぐに、鏡の映像を出す
  const form = document.getElementById("plea-form");
  const waiting = document.querySelector("[data-mirror-waiting]");
  if (!form || !waiting) return;
  form.addEventListener("submit", (e) => {
    const button = e.submitter;
    if (!button || !button.hasAttribute("data-reflect")) return;
    waiting.hidden = false;
    fitAll();
    waiting.scrollIntoView({ block: "center", behavior: "smooth" });
    // 送信が始まったあとに、ボタンを押せなくする（二重押しを防ぐ）
    setTimeout(() => {
      form.querySelectorAll("button").forEach((b) => { b.disabled = true; });
    }, 0);
  });
})();
