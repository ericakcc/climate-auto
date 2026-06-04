"use strict";

/*
 * Climate Auto — local weather-report editor.
 * Vanilla JS controller for the full pipeline: collect -> extract -> synthesize,
 * an editable extraction area, a live SSE log console, and a rendered report.
 *
 * API contract (same-origin):
 *   GET  /api/job            -> {running, job_id?, kind?, date?}
 *   GET  /api/dates          -> {dates:[{date, has_report_dir, has_extractions, has_daily_report}]}
 *   GET  /api/extractions?date=YYYY-MM-DD -> {date, blocks:[{key,text,exists,image_url|null}]}
 *   PUT  /api/extractions    body {date, blocks:[...]} -> {path, count}
 *   GET  /api/report?date=.. -> {date, markdown, image_base}
 *   POST /api/collect|extract|synthesize  body {date, numeric} -> {job_id} | 409 {detail}
 *   GET  /api/stream/{job_id} (SSE: log / done / error)
 */

(function () {
  // ---- element handles ----------------------------------------------------
  const $ = (id) => document.getElementById(id);
  const els = {
    progress: $("progress"),
    statusDot: $("statusDot"),
    statusEyebrow: $("statusEyebrow"),
    dateSelect: $("dateSelect"),
    loadBtn: $("loadBtn"),
    newDateInput: $("newDateInput"),
    addDateBtn: $("addDateBtn"),
    reloadDatesBtn: $("reloadDatesBtn"),
    btnCollect: $("btnCollect"),
    btnExtract: $("btnExtract"),
    btnSynthesize: $("btnSynthesize"),
    numericChk: $("numericChk"),
    notice: $("notice"),
    noticeText: $("noticeText"),
    noticeClose: $("noticeClose"),
    saveBtn: $("saveBtn"),
    saveHint: $("saveHint"),
    blocks: $("blocks"),
    blocksHint: $("blocksHint"),
    blocksPlaceholder: $("blocksPlaceholder"),
    logLamp: $("logLamp"),
    logState: $("logState"),
    clearLogBtn: $("clearLogBtn"),
    console: $("console"),
    reportSection: $("reportSection"),
    reportBody: $("reportBody"),
    reportMeta: $("reportMeta"),
    reportHint: $("reportHint"),
  };

  // ---- mutable state ------------------------------------------------------
  const state = {
    job: null, // current EventSource
    jobKind: null, // "collect" | "extract" | "synthesize"
    running: false,
    loadedDate: null, // date whose blocks are currently shown
  };

  // ---- small helpers ------------------------------------------------------
  function showNotice(kind, text) {
    els.notice.className = "notice show " + kind;
    els.noticeText.textContent = text;
  }
  function hideNotice() {
    els.notice.className = "notice";
  }

  async function fetchJSON(url, opts) {
    const resp = await fetch(url, opts);
    let body = null;
    try {
      body = await resp.json();
    } catch (_) {
      body = null;
    }
    return { ok: resp.ok, status: resp.status, body };
  }

  // ---- log console --------------------------------------------------------
  function appendLog(line) {
    const div = document.createElement("div");
    div.className = "ln " + (line.cls || "");
    if (line.time) {
      const t = document.createElement("span");
      t.className = "t";
      t.textContent = line.time;
      div.appendChild(t);
    }
    const m = document.createElement("span");
    m.className = "m";
    m.textContent = line.text;
    div.appendChild(m);
    els.console.appendChild(div);
    // auto-scroll to bottom
    els.console.scrollTop = els.console.scrollHeight;
  }
  function logSystem(text) {
    appendLog({ cls: "sys", text: text });
  }
  function clearLog() {
    els.console.innerHTML = "";
  }

  function setLogState(mode, label) {
    // mode: "idle" | "live" | "err"
    els.logLamp.className = "lamp" + (mode === "live" ? " live" : mode === "err" ? " err" : "");
    els.logState.textContent = label;
  }

  // ---- run-state / button enabling ---------------------------------------
  const runButtons = [els.btnCollect, els.btnExtract, els.btnSynthesize];

  function setRunning(running, kind) {
    state.running = running;
    state.jobKind = running ? kind : null;
    runButtons.forEach((b) => (b.disabled = running));
    els.numericChk.disabled = running;
    // Save would clobber extractions.md mid-extract; lock it only for extract jobs.
    els.saveBtn.disabled = running && kind === "extract";
    if (running && kind === "extract") {
      els.saveHint.textContent = "萃取進行中，暫停存檔以免覆寫。";
    } else {
      els.saveHint.textContent = "讀取每個區塊的目前內容寫回 extractions.md。";
    }
    // ambient cues
    els.progress.className = "progress " + (running ? "run" : "idle");
    els.statusDot.className = "dot" + (running ? " busy" : "");
    if (running) {
      const labelMap = { collect: "蒐集中", extract: "萃取中", synthesize: "統整中" };
      els.statusEyebrow.textContent =
        "CLIMATE AUTO · " + (labelMap[kind] || "執行中") + "…";
    } else {
      els.statusEyebrow.textContent = "CLIMATE AUTO · 本地報告編輯器";
    }
  }

  // ---- date <select> ------------------------------------------------------
  function badgeText(info) {
    const flags = [];
    if (info.has_report_dir) flags.push("dir");
    if (info.has_extractions) flags.push("萃取");
    if (info.has_daily_report) flags.push("報告");
    return flags.length ? "  [" + flags.join(" · ") + "]" : "  [空]";
  }

  async function loadDates(selectDate) {
    const prev = selectDate || els.dateSelect.value || null;
    const res = await fetchJSON("/api/dates");
    if (!res.ok || !res.body) {
      showNotice("err", "無法載入日期清單（HTTP " + res.status + "）。");
      return;
    }
    const dates = (res.body.dates || []).slice(); // already most-recent-first
    els.dateSelect.innerHTML = "";
    if (!dates.length) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "（尚無任何資料日期）";
      els.dateSelect.appendChild(opt);
      els.dateSelect.disabled = true;
      return;
    }
    els.dateSelect.disabled = false;
    dates.forEach((info) => {
      const opt = document.createElement("option");
      opt.value = info.date;
      opt.textContent = info.date + badgeText(info);
      els.dateSelect.appendChild(opt);
    });
    // preserve selection if still present, else default to most-recent
    if (prev && dates.some((d) => d.date === prev)) {
      els.dateSelect.value = prev;
    } else {
      els.dateSelect.value = dates[0].date;
    }
  }

  function currentDate() {
    return els.dateSelect.value || "";
  }

  function todayLocal() {
    const d = new Date();
    const p = (n) => String(n).padStart(2, "0");
    return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate());
  }

  // Add a brand-new date (not yet collected) to the picker and select it, so
  // the user can run Collect on it. The backend creates the folder on collect.
  function addDate() {
    const value = els.newDateInput.value;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
      showNotice("warn", "請先選擇有效日期（YYYY-MM-DD）。");
      return;
    }
    const exists = [...els.dateSelect.options].some((o) => o.value === value);
    if (!exists) {
      const opt = document.createElement("option");
      opt.value = value;
      opt.textContent = value + "  [新]";
      els.dateSelect.insertBefore(opt, els.dateSelect.firstChild);
    }
    els.dateSelect.disabled = false;
    els.dateSelect.value = value;
    showNotice("ok", `已新增 ${value}，按「蒐集 Collect」開始下載資料。`);
    loadExtractions(value);
  }

  // ---- extraction blocks --------------------------------------------------
  function renderPlaceholder(big, sub) {
    els.blocks.innerHTML = "";
    const card = document.createElement("div");
    card.className = "page placeholder-card";
    const b = document.createElement("div");
    b.className = "big";
    b.textContent = big;
    const s = document.createElement("div");
    s.textContent = sub;
    card.appendChild(b);
    card.appendChild(s);
    els.blocks.appendChild(card);
  }

  const PROV = {
    numeric: { cls: "num", label: "數值計算", edge: "e-num" },
    observation: { cls: "obs", label: "觀測資料", edge: "e-obs" },
    vision: { cls: "vis", label: "AI 讀圖", edge: "e-vis" },
  };

  function buildBlockCard(block) {
    const prov = PROV[block.provenance] || PROV.vision;
    const card = document.createElement("div");
    card.className = "page block-card " + prov.edge;
    card.dataset.key = block.key;

    // head: key label + provenance pill
    const head = document.createElement("div");
    head.className = "bc-head";
    const keyEl = document.createElement("span");
    keyEl.className = "bc-key";
    keyEl.textContent = block.key;
    head.appendChild(keyEl);

    const pill = document.createElement("span");
    pill.className = "prov " + prov.cls;
    pill.innerHTML = '<span class="sq"></span>' + prov.label;
    head.appendChild(pill);

    if (block.provenance === "vision" && !block.exists && block.image_url == null) {
      const flag = document.createElement("span");
      flag.className = "bc-flag";
      flag.textContent = "無對應圖檔";
      head.appendChild(flag);
    }
    card.appendChild(head);

    // body grid: optional image + textarea
    const grid = document.createElement("div");
    grid.className = "bc-grid" + (block.image_url ? "" : " noimg");

    if (block.image_url) {
      const fig = document.createElement("figure");
      fig.className = "chart";
      const img = document.createElement("img");
      img.loading = "lazy";
      img.src = block.image_url;
      img.alt = block.key;
      const cap = document.createElement("figcaption");
      const left = document.createElement("span");
      left.textContent = block.key;
      const right = document.createElement("span");
      right.textContent =
        block.provenance === "vision" ? "AI 讀圖來源" : "圖供對照（數字來自格點）";
      cap.appendChild(left);
      cap.appendChild(right);
      fig.appendChild(img);
      fig.appendChild(cap);
      grid.appendChild(fig);
    }

    const ta = document.createElement("textarea");
    ta.className = "bc-ta";
    ta.value = block.text || "";
    ta.spellcheck = false;
    ta.dataset.key = block.key;
    // remember provenance bits so Save can faithfully echo them back
    ta.dataset.exists = block.exists ? "1" : "0";
    ta.dataset.imageUrl = block.image_url == null ? "" : block.image_url;
    autoGrow(ta);
    ta.addEventListener("input", () => autoGrow(ta));
    grid.appendChild(ta);

    card.appendChild(grid);
    return card;
  }

  function autoGrow(ta) {
    ta.style.height = "auto";
    ta.style.height = Math.max(120, ta.scrollHeight + 2) + "px";
  }

  async function loadExtractions(dateStr) {
    if (!dateStr) {
      showNotice("warn", "請先選擇一個資料日期。");
      return;
    }
    els.blocksHint.textContent = "載入中…";
    const res = await fetchJSON("/api/extractions?date=" + encodeURIComponent(dateStr));

    if (res.status === 404) {
      state.loadedDate = dateStr;
      renderPlaceholder("尚無資料", "尚無資料，請先 Collect。");
      els.blocksHint.textContent = dateStr + " · 尚無 report 目錄";
      return;
    }
    if (!res.ok || !res.body) {
      const detail = (res.body && res.body.detail) || "HTTP " + res.status;
      showNotice("err", "載入萃取失敗：" + detail);
      els.blocksHint.textContent = "載入失敗";
      return;
    }

    state.loadedDate = dateStr;
    const blocks = res.body.blocks || [];
    if (!blocks.length) {
      renderPlaceholder("尚未萃取", "尚未萃取，請先 Extract。");
      els.blocksHint.textContent = dateStr + " · 0 個區塊";
      return;
    }

    els.blocks.innerHTML = "";
    const frag = document.createDocumentFragment();
    blocks.forEach((b) => frag.appendChild(buildBlockCard(b)));
    els.blocks.appendChild(frag);
    els.blocksHint.textContent = dateStr + " · " + blocks.length + " 個區塊";
  }

  async function saveExtractions() {
    const dateStr = state.loadedDate || currentDate();
    const textareas = els.blocks.querySelectorAll("textarea.bc-ta");
    if (!dateStr || !textareas.length) {
      showNotice("warn", "沒有可儲存的萃取區塊。");
      return;
    }
    const blocks = [];
    textareas.forEach((ta) => {
      blocks.push({
        key: ta.dataset.key,
        text: ta.value,
        exists: ta.dataset.exists === "1",
        image_url: ta.dataset.imageUrl ? ta.dataset.imageUrl : null,
      });
    });

    els.saveBtn.disabled = true;
    const prevHint = els.saveHint.textContent;
    els.saveHint.textContent = "儲存中…";
    try {
      const res = await fetchJSON("/api/extractions", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ date: dateStr, blocks: blocks }),
      });
      if (!res.ok) {
        const detail = (res.body && res.body.detail) || "HTTP " + res.status;
        showNotice("err", "儲存失敗：" + detail);
        els.saveHint.textContent = prevHint;
        return;
      }
      const count = res.body && res.body.count != null ? res.body.count : blocks.length;
      showNotice("ok", "已儲存 " + count + " 個區塊 ✓");
      els.saveHint.textContent = "已儲存於 " + (new Date()).toLocaleTimeString() + "。";
    } catch (err) {
      showNotice("err", "儲存失敗：" + (err && err.message ? err.message : err));
      els.saveHint.textContent = prevHint;
    } finally {
      // never leave Save permanently disabled (unless an extract job is running)
      if (!(state.running && state.jobKind === "extract")) els.saveBtn.disabled = false;
    }
  }

  // ---- rendered report ----------------------------------------------------
  async function loadReport(dateStr) {
    if (!dateStr) return;
    const res = await fetchJSON("/api/report?date=" + encodeURIComponent(dateStr));
    if (!res.ok || !res.body) {
      const detail = (res.body && res.body.detail) || "HTTP " + res.status;
      showNotice("warn", "無法載入產出報告：" + detail);
      return;
    }
    renderReport(res.body);
  }

  function renderReport(payload) {
    const markdown = payload.markdown || "";
    const imageBase = payload.image_base || "";
    els.reportSection.classList.remove("hidden");
    els.reportMeta.textContent =
      "data/" + payload.date + "/report/daily_report.md · 客戶端渲染";
    els.reportHint.textContent = payload.date;

    const hasLibs =
      typeof window.marked !== "undefined" && typeof window.DOMPurify !== "undefined";

    if (hasLibs) {
      let rawHtml;
      try {
        rawHtml =
          typeof window.marked.parse === "function"
            ? window.marked.parse(markdown)
            : window.marked(markdown);
      } catch (_) {
        rawHtml = null;
      }
      if (rawHtml != null) {
        const clean = window.DOMPurify.sanitize(rawHtml);
        els.reportBody.innerHTML = clean;
        rewriteImages(imageBase);
        els.reportSection.scrollIntoView({ behavior: "smooth", block: "start" });
        return;
      }
    }
    // fallback: raw markdown in a <pre>
    els.reportBody.innerHTML = "";
    const pre = document.createElement("pre");
    pre.className = "report-raw";
    pre.textContent = markdown;
    els.reportBody.appendChild(pre);
    els.reportSection.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function rewriteImages(imageBase) {
    // image_base already equals "/api/image?date=...&path="
    const imgs = els.reportBody.querySelectorAll("img");
    imgs.forEach((img) => {
      const rel = img.getAttribute("src") || "";
      if (!rel) return;
      if (rel.indexOf("http") === 0 || rel.charAt(0) === "/") return; // already absolute
      img.setAttribute("src", imageBase + encodeURIComponent(rel));
      img.setAttribute("loading", "lazy");
    });
  }

  // ---- SSE wiring ---------------------------------------------------------
  function closeStream() {
    if (state.job) {
      try {
        state.job.close();
      } catch (_) {}
      state.job = null;
    }
  }

  function connectStream(jobId, kind) {
    closeStream();
    const es = new EventSource("/api/stream/" + encodeURIComponent(jobId));
    state.job = es;
    setRunning(true, kind);
    setLogState("live", "串流中 · " + (kind || "job"));

    // 'log' events: {level, time, text}
    es.addEventListener("log", (ev) => {
      let d;
      try {
        d = JSON.parse(ev.data);
      } catch (_) {
        return;
      }
      const lvl = (d.level || "INFO").toUpperCase();
      const cls = lvl === "ERROR" ? "err" : lvl === "WARNING" ? "warn" : "";
      appendLog({ time: d.time || "", cls: cls, text: d.text != null ? d.text : "" });
    });

    // 'done' events: {} or {report_url}
    es.addEventListener("done", (ev) => {
      let d = {};
      try {
        d = ev.data ? JSON.parse(ev.data) : {};
      } catch (_) {
        d = {};
      }
      logSystem("✓ 任務完成（" + kind + "）");
      setLogState("idle", "完成 DONE");
      finishJob(kind, d);
    });

    // 'error' events: {message}
    es.addEventListener("error", (ev) => {
      // EventSource also fires a generic 'error' on transient disconnects;
      // only treat as fatal when the server sent a payload.
      if (ev && ev.data) {
        let d = {};
        try {
          d = JSON.parse(ev.data);
        } catch (_) {
          d = {};
        }
        const msg = d.message || "未知錯誤";
        appendLog({ cls: "err", text: "✗ 錯誤：" + msg });
        showNotice("err", "任務失敗：" + msg);
        setLogState("err", "錯誤 ERROR");
        finishJob(kind, null, true);
      } else if (es.readyState === EventSource.CLOSED) {
        // connection closed unexpectedly — recover the UI so buttons aren't stuck.
        logSystem("連線中斷。");
        setLogState("idle", "中斷");
        endRun();
      }
    });
  }

  function endRun() {
    closeStream();
    setRunning(false, null);
  }

  async function finishJob(kind, doneData, errored) {
    endRun();
    if (errored) {
      await loadDates(currentDate());
      return;
    }
    // refresh date list (artifacts may now exist)
    await loadDates(currentDate());
    if (kind === "extract") {
      await loadExtractions(state.loadedDate || currentDate());
    }
    if (doneData && doneData.report_url) {
      // synthesize finished: render the produced report
      await loadReport(currentDate());
    } else if (kind === "synthesize") {
      await loadReport(currentDate());
    }
  }

  // ---- starting jobs ------------------------------------------------------
  async function startJob(endpoint, kind) {
    if (state.running) {
      showNotice("warn", "已有任務執行中，請待其完成。");
      return;
    }
    const dateStr = currentDate();
    if (!dateStr) {
      showNotice("warn", "請先選擇一個資料日期。");
      return;
    }
    hideNotice();
    const payload = { date: dateStr, numeric: !!els.numericChk.checked };
    logSystem(
      "→ 啟動 " + kind + "（date=" + dateStr + ", numeric=" + payload.numeric + "）",
    );
    let res;
    try {
      res = await fetchJSON(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    } catch (err) {
      showNotice("err", "無法啟動任務：" + (err && err.message ? err.message : err));
      logSystem("✗ 啟動失敗");
      return;
    }
    if (res.status === 409) {
      const detail = (res.body && res.body.detail) || "已有另一個任務在執行";
      showNotice("warn", detail);
      logSystem("✗ 409 " + detail);
      return;
    }
    if (!res.ok || !res.body || !res.body.job_id) {
      const detail = (res.body && res.body.detail) || "HTTP " + res.status;
      showNotice("err", "啟動失敗：" + detail);
      logSystem("✗ " + detail);
      return;
    }
    connectStream(res.body.job_id, kind);
  }

  // ---- initial load / reconnect ------------------------------------------
  async function init() {
    await loadDates();

    // reconnect to a job already in progress (page reloaded mid-run)
    const jobRes = await fetchJSON("/api/job");
    if (jobRes.ok && jobRes.body && jobRes.body.running && jobRes.body.job_id) {
      logSystem("偵測到執行中任務（" + jobRes.body.kind + "），重新連接日誌串流…");
      if (jobRes.body.date) {
        // align the selector with the running job
        if ([...els.dateSelect.options].some((o) => o.value === jobRes.body.date)) {
          els.dateSelect.value = jobRes.body.date;
        }
      }
      connectStream(jobRes.body.job_id, jobRes.body.kind);
    } else {
      setRunning(false, null);
      setLogState("idle", "閒置 IDLE");
    }

    // auto-load extractions for the initially selected date
    if (currentDate()) {
      await loadExtractions(currentDate());
    }
  }

  // ---- events -------------------------------------------------------------
  els.loadBtn.addEventListener("click", () => loadExtractions(currentDate()));
  els.dateSelect.addEventListener("change", () => loadExtractions(currentDate()));
  els.newDateInput.value = todayLocal();
  els.addDateBtn.addEventListener("click", addDate);
  els.reloadDatesBtn.addEventListener("click", () => loadDates(currentDate()));
  els.btnCollect.addEventListener("click", () => startJob("/api/collect", "collect"));
  els.btnExtract.addEventListener("click", () => startJob("/api/extract", "extract"));
  els.btnSynthesize.addEventListener("click", () =>
    startJob("/api/synthesize", "synthesize"),
  );
  els.saveBtn.addEventListener("click", saveExtractions);
  els.clearLogBtn.addEventListener("click", clearLog);
  els.noticeClose.addEventListener("click", hideNotice);

  // kick off
  init().catch((err) => {
    showNotice("err", "初始化失敗：" + (err && err.message ? err.message : err));
  });
})();
