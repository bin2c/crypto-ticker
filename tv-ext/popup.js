const PORTS = Array.from({ length: 10 }, (_, i) => 17653 + i);

function $(id) { return document.getElementById(id); }

function fmtTime(ts) {
  if (!ts) return "-";
  const d = new Date(ts);
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

async function probe() {
  for (const p of PORTS) {
    try {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 700);
      const r = await fetch("http://127.0.0.1:" + p + "/ping", { cache: "no-store", signal: ctrl.signal });
      clearTimeout(timer);
      if (!r.ok) continue;
      const j = await r.json();
      if (j && j.app === "crypto-ticker") return { port: p, info: j };
    } catch (e) {}
  }
  return null;
}

async function main() {
  const store = await chrome.storage.local.get(["last", "online", "error"]);
  const last = store.last || null;
  const found = await probe();

  $("port").textContent = found ? "127.0.0.1:" + found.port : "未找到";
  $("port").className = "v " + (found ? "ok" : "bad");

  $("sym").textContent = last ? last.symbol : (found && found.info.symbol ? found.info.symbol : "-");
  $("res").textContent = found ? "在线" : "行情条没开";
  $("res").className = "v " + (found ? "ok" : "bad");
  $("at").textContent = last ? fmtTime(last.at) : "-";

  if (found) {
    const j = found.info;
    $("hint").textContent = "在行情条里点品种，或在扫盘页按 ↑ ↓；"
      + "当前 TV 品种：" + (j.symbol || "（还没有）") + "。";
  } else {
    $("hint").textContent = store.error || "先打开行情条（ticker），再回来。";
  }
}

main();
