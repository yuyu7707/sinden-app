// 祠の画面：相手の灯り、持ち時間、画面の作り直し、下書きの保存、声で訴える
(() => {
  const shrine = document.querySelector(".shrine");
  if (!shrine) return;

  const stateUrl = shrine.dataset.stateUrl;
  const version = shrine.dataset.version;
  const visitId = shrine.querySelector(".stage")?.dataset.visit;
  // 下書きは「利用者・祠・番ごと」に分ける。次の番に前の文章が残らず、
  // 同じブラウザで別の人がログインしても、前の人の文章は出ない
  const draftKey = `sinden-draft-${shrine.dataset.user}-${visitId}-${shrine.dataset.turn}`;

  const safeGet = (key) => { try { return sessionStorage.getItem(key); } catch { return null; } };
  const safeSet = (key, value) => { try { sessionStorage.setItem(key, value); } catch { /* 使えなくても動く */ } };
  const safeRemove = (key) => { try { sessionStorage.removeItem(key); } catch { /* 同上 */ } };

  // 近づく演出は、同じ訪問で1回だけ
  const stage = shrine.querySelector(".stage.intro");
  if (stage) {
    const key = `sinden-intro-${visitId}`;
    if (safeGet(key)) stage.classList.remove("intro");
    else safeSet(key, "1");
  }

  // ---- 持ち時間 ----
  const timer = document.getElementById("timer");
  const form = document.getElementById("plea-form");
  let remaining = timer ? Number(timer.dataset.remaining) : 0;
  let submitted = false;
  const render = () => {
    if (!timer) return;
    const m = Math.floor(remaining / 60);
    const s = String(remaining % 60).padStart(2, "0");
    timer.textContent = `${m}:${s}`;
  };
  // 持ち時間が0になっても、自動では届けない（届くのは、本人が「届ける」を押した言葉だけ）。
  // 「1分以内なら届けられる」と知らせる。サーバーは、持ち時間の60秒後に番を相手に渡す
  const timeUp = document.getElementById("time-up");
  if (timer) {
    setInterval(() => {
      remaining = Math.max(0, remaining - 1);
      render();
      if (remaining === 0 && timeUp && !timer.dataset.passive) timeUp.hidden = false;
    }, 1000);
  }

  // ---- 下書きの保存（画面が作り直されても消えないように）----
  const body = document.getElementById("plea-body");
  const count = document.getElementById("count");
  if (body) {
    // 一時保存があれば戻す（「ことばを確かめる」のあとは、サーバーが入れた下書きを優先する）
    const saved = safeGet(draftKey);
    if (saved !== null) body.value = saved;
    const update = () => {
      if (count) count.textContent = body.value.length;
      safeSet(draftKey, body.value);
    };
    body.addEventListener("input", update);
    update();
    form.addEventListener("submit", () => { submitted = true; safeRemove(draftKey); });
  }
  // 「ことばの灯の言い方で届ける」など、別のフォームで届けたときも下書きを消す
  shrine.querySelectorAll("form").forEach((f) => {
    if (f.querySelector('input[name="source"]')) {
      f.addEventListener("submit", () => { submitted = true; safeRemove(draftKey); });
    }
  });

  // ---- 相手の様子を数秒ごとに確かめる ----
  const partnerLight = shrine.querySelector(".light.partner");
  const presence = shrine.querySelector("[data-presence]");
  const partnerName = partnerLight?.getAttribute("title") || "相手";
  const poll = async () => {
    try {
      const res = await fetch(stateUrl, { headers: { Accept: "application/json" } });
      if (res.status === 404 || res.redirected) {
        // 祠が消えた・ペアでなくなった（相手の退会など）。ホームへ戻る
        location.href = shrine.dataset.homeUrl;
        return;
      }
      if (!res.ok) return;
      const data = await res.json();
      if (data.version !== version && !submitted) {
        location.reload();
        return;
      }
      partnerLight?.classList.toggle("on", data.partner_present);
      if (presence) {
        presence.textContent = data.partner_present
          ? `${partnerName}さんが隣で聴いています`
          : `${partnerName}さんの灯りが消えています`;
      }
      if (timer && Math.abs(data.remaining - remaining) > 3) {
        remaining = data.remaining;
        render();
      }
    } catch {
      // 通信が切れても、次の回で取り直す
    }
  };
  setInterval(poll, 3000);

  // ---- 声で訴える（プラン。ブラウザの音声認識を使う。費用はかからない）----
  const voice = document.getElementById("voice");
  const live = document.getElementById("voice-live");
  const unsupported = document.getElementById("voice-unsupported");
  const myLight = shrine.querySelector(".light:not(.partner)");
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (voice && body && !Recognition && unsupported) unsupported.hidden = false;
  if (voice && body && Recognition) {
    voice.hidden = false;
    const label = voice.querySelector(".voice-label");
    const rec = new Recognition();
    rec.lang = "ja-JP";
    rec.continuous = true;
    rec.interimResults = true; // 話している途中の言葉も、その場で見せる
    let listening = false;

    const setListening = (on) => {
      listening = on;
      voice.classList.toggle("listening", on);
      myLight?.classList.toggle("voice-on", on);
      label.textContent = on ? "話し終えたら、もう一度押す" : "女神に、声で話しかける";
      if (!on && live) live.textContent = "";
    };

    rec.onresult = (event) => {
      let interim = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const text = event.results[i][0].transcript;
        if (event.results[i].isFinal) {
          body.value += text;
          body.dispatchEvent(new Event("input"));
        } else {
          interim += text;
        }
      }
      if (live) live.textContent = interim;
    };
    rec.onend = () => {
      if (listening) rec.start(); // 無音で止まっても、押している間は聞き続ける
    };
    rec.onerror = (event) => {
      if (event.error === "not-allowed" || event.error === "service-not-allowed") {
        setListening(false);
        if (live) live.textContent = "マイクの使用が許可されていません。ブラウザの設定を確認してください。";
      }
    };
    voice.addEventListener("click", () => {
      if (listening) {
        setListening(false);
        rec.stop();
      } else {
        setListening(true);
        rec.start();
      }
    });
    // 届ける・映すときは、声を止める
    form?.addEventListener("submit", () => {
      if (listening) {
        listening = false;
        rec.stop();
      }
    });
  }
})();
