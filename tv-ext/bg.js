// 行情条 · TradingView 联动
//
// 分工：
//   ticker.py 里有个 TVBridge，在 127.0.0.1:17653-17662 上广播
//   「当前该看哪个品种」；这里轮询它（长轮询，切品种后几乎立刻返回），
//   再把 setSymbol 注入**用户自己的 TradingView 标签页**。
//
// 为什么是注入而不是跳转：
//   TradingView 页面里的 _exposed_chartWidgetCollection.setSymbol()
//   能在不刷新、不丢画线/布局的情况下换品种；整页跳转则要重新加载 2~4 秒，
//   扫盘时按 ↑↓ 会非常卡。

const PORTS = Array.from({ length: 10 }, (_, i) => 17653 + i);
const TV_TAB_PATTERNS = ["https://cn.tradingview.com/*", "https://www.tradingview.com/*"];
const CHART_URL = "https://www.tradingview.com/chart/?symbol=";

let bridgePort = 0;
let seq = -1;
let started = false;
let lastError = "";
let preferredTabId = 0;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function log() {
  try {
    console.log("[tv-link]", ...arguments);
  } catch (e) {}
}

async function setBadge(text, color) {
  try {
    await chrome.action.setBadgeText({ text });
    if (color) await chrome.action.setBadgeBackgroundColor({ color });
  } catch (e) {}
}

async function probe() {
  for (const p of PORTS) {
    try {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 900);
      const r = await fetch("http://127.0.0.1:" + p + "/ping", { cache: "no-store", signal: ctrl.signal });
      clearTimeout(timer);
      if (!r.ok) continue;
      const j = await r.json();
      if (j && j.app === "crypto-ticker") {
        bridgePort = p;
        return j;
      }
    } catch (e) {}
  }
  return null;
}

// 注入到页面主世界执行：这段函数会被序列化，不能引用外部变量
function injectedSetSymbol(sym) {
  try {
    const c = window._exposed_chartWidgetCollection;
    if (c && typeof c.setSymbol === "function") {
      c.setSymbol(sym);
      return "ok";
    }
  } catch (e) {
    return "err:" + e;
  }
  return "no-collection";
}

async function tvTabs() {
  const seen = new Set();
  const out = [];
  for (const pattern of TV_TAB_PATTERNS) {
    let tabs = [];
    try {
      tabs = await chrome.tabs.query({ url: pattern });
    } catch (e) {
      tabs = [];
    }
    for (const t of tabs) {
      if (t && t.id && !seen.has(t.id)) {
        seen.add(t.id);
        out.push(t);
      }
    }
  }
  return out;
}

async function inject(tabId, sym) {
  try {
    const out = await chrome.scripting.executeScript({
      target: { tabId },
      world: "MAIN",
      func: injectedSetSymbol,
      args: [sym],
    });
    return (out && out[0] && out[0].result) || "empty";
  } catch (e) {
    return "inject:" + (e && e.message ? e.message : e);
  }
}

function isChartTab(tab) {
  return !!tab && /\/chart/.test(tab.url || "");
}

async function pickTab() {
  const tabs = await tvTabs();
  if (!tabs.length) return null;
  const chartTabs = tabs.filter(isChartTab);
  const pool = chartTabs.length ? chartTabs : tabs;
  // 1) 上次成功推送过的那个  2) 当前激活的  3) 最后一个
  const preferred = pool.find((t) => t.id === preferredTabId);
  if (preferred) return preferred;
  return pool.find((t) => t.active) || pool[pool.length - 1];
}

async function apply(sym) {
  let tab = await pickTab();
  if (!tab) {
    const created = await chrome.tabs.create({ url: CHART_URL + encodeURIComponent(sym), active: false });
    preferredTabId = created.id;
    await noteResult(sym, "新开标签页");
    return;
  }

  let res = await inject(tab.id, sym);
  // 刚打开的图表还没初始化（no-collection）时再试几次；页面可能正在加载
  for (let i = 0; i < 3 && res !== "ok"; i++) {
    await sleep(800);
    res = await inject(tab.id, sym);
  }

  if (res !== "ok") {
    // 兜底：整页跳到正确品种（会重载，但至少品种对）
    if (isChartTab(tab)) {
      await chrome.tabs.update(tab.id, { url: CHART_URL + encodeURIComponent(sym) });
      await noteResult(sym, "整页跳转（图表未初始化：" + res + "）");
    } else {
      const created = await chrome.tabs.create({ url: CHART_URL + encodeURIComponent(sym), active: false });
      preferredTabId = created.id;
      await noteResult(sym, "新开图表标签页");
    }
    return;
  }

  preferredTabId = tab.id;
  await noteResult(sym, "已切换");
}

async function noteResult(symbol, result) {
  try {
    await chrome.storage.local.set({
      last: { symbol, result, at: Date.now(), tl: String(symbol).split(":").pop() },
      online: true,
      error: "",
    });
  } catch (e) {}
}

async function loop() {
  if (started) return;
  started = true;
  for (;;) {
    try {
      if (!bridgePort) {
        const info = await probe();
        if (!info) {
          lastError = "找不到行情条（ticker 没开，或 17653-17662 端口被占）";
          try { await chrome.storage.local.set({ online: false, error: lastError }); } catch (e) {}
          await setBadge("?", "#777");
          await sleep(2500);
          continue;
        }
        // 刚连上：记住当前 seq，不回放上一次的品种
        seq = typeof info.seq === "number" ? info.seq : 0;
        lastError = "";
        await setBadge("✓", "#2f7d32");
        try { await chrome.storage.local.set({ online: true, error: "", port: bridgePort }); } catch (e) {}
      }

      const r = await fetch(
        "http://127.0.0.1:" + bridgePort + "/state?since=" + seq + "&wait=20",
        { cache: "no-store" }
      );
      const j = await r.json();
      if (j && typeof j.seq === "number" && j.seq !== seq) {
        seq = j.seq;
        if (j.symbol) {
          await setBadge("•", "#1565c0");
          await apply(j.symbol);
          await setBadge("✓", "#2f7d32");
        }
      }
    } catch (e) {
      lastError = (e && e.message) || String(e);
      bridgePort = 0;
      seq = -1;
      try { await chrome.storage.local.set({ online: false, error: lastError }); } catch (e2) {}
      await setBadge("!", "#b00020");
      await sleep(1500);
    }
  }
}

// MV3 的 service worker 会被回收：闹钟负责把它叫醒并重启轮询
function keepAlive() {
  try {
    chrome.alarms.create("tv-link-keepalive", { periodInMinutes: 0.5 });
  } catch (e) {}
}

chrome.runtime.onInstalled.addListener(() => {
  keepAlive();
  loop();
});
chrome.runtime.onStartup.addListener(() => {
  keepAlive();
  loop();
});
chrome.alarms.onAlarm.addListener((alarm) => {
  if (!alarm || alarm.name === "tv-link-keepalive") loop();
});
// 任何时候被唤醒（点开 popup 等）都保证轮询在跑
keepAlive();
loop();
