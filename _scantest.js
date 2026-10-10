// 全品种扫盘页测试（真浏览器 + 真键盘事件）
// 验：全量名单（含 TradFi 黄金/股票）、分类筛选、搜索、↑↓ 快速切图、点选、无异常。
const net = require('net');
const crypto = require('crypto');
const http = require('http');
const { spawn } = require('child_process');

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const PORT = 9356;
const base_url = process.argv[2];
const scan_url = base_url.replace(/\/$/, '') + '/scan';
const sleep = ms => new Promise(r => setTimeout(r, ms));

const getJson = p => new Promise((res, rej) => {
  http.get({ host: '127.0.0.1', port: PORT, path: p }, r => {
    let b = ''; r.on('data', d => (b += d));
    r.on('end', () => { try { res(JSON.parse(b)); } catch (e) { rej(e); } });
  }).on('error', rej);
});

class MiniWS {
  constructor(url) {
    const u = new URL(url);
    this.buf = Buffer.alloc(0); this.handlers = [];
    this.sock = net.connect(Number(u.port), u.hostname);
    this.ready = new Promise((resolve, reject) => {
      const key = crypto.randomBytes(16).toString('base64');
      this.sock.on('connect', () => this.sock.write(
        `GET ${u.pathname}${u.search} HTTP/1.1\r\nHost: ${u.host}\r\n` +
        `Upgrade: websocket\r\nConnection: Upgrade\r\n` +
        `Sec-WebSocket-Key: ${key}\r\nSec-WebSocket-Version: 13\r\n\r\n`));
      this.sock.on('error', reject);
      let hs = false;
      this.sock.on('data', chunk => {
        this.buf = Buffer.concat([this.buf, chunk]);
        if (!hs) {
          const i = this.buf.indexOf('\r\n\r\n');
          if (i < 0) return;
          const head = this.buf.subarray(0, i).toString();
          if (!/101/.test(head)) return reject(new Error(head.split('\r\n')[0]));
          hs = true; this.buf = this.buf.subarray(i + 4); resolve();
        }
        this._drain();
      });
    });
  }
  _drain() {
    for (;;) {
      const b = this.buf;
      if (b.length < 2) return;
      const op = b[0] & 0x0f;
      let len = b[1] & 0x7f, off = 2;
      if (len === 126) { if (b.length < 4) return; len = b.readUInt16BE(2); off = 4; }
      else if (len === 127) { if (b.length < 10) return; len = Number(b.readBigUInt64BE(2)); off = 10; }
      if (b.length < off + len) return;
      const payload = b.subarray(off, off + len);
      this.buf = b.subarray(off + len);
      if (op === 1) this.handlers.forEach(h => h(payload.toString('utf8')));
      else if (op === 8) { this.sock.end(); return; }
    }
  }
  onMessage(f) { this.handlers.push(f); }
  send(str) {
    const data = Buffer.from(str, 'utf8'), mask = crypto.randomBytes(4);
    let head;
    if (data.length < 126) head = Buffer.from([0x81, 0x80 | data.length]);
    else if (data.length < 65536) {
      head = Buffer.alloc(4); head[0] = 0x81; head[1] = 0x80 | 126;
      head.writeUInt16BE(data.length, 2);
    } else {
      head = Buffer.alloc(10); head[0] = 0x81; head[1] = 0x80 | 127;
      head.writeBigUInt64BE(BigInt(data.length), 2);
    }
    const masked = Buffer.alloc(data.length);
    for (let i = 0; i < data.length; i++) masked[i] = data[i] ^ mask[i % 4];
    this.sock.write(Buffer.concat([head, mask, masked]));
  }
  close() { try { this.sock.destroy(); } catch (_) {} }
}

let passed = 0, total = 0;
const check = (label, cond, extra = '') => {
  total++;
  if (cond) passed++;
  console.log(`  ${cond ? '[OK]' : '[NG]'} ${label}${extra ? '   ' + extra : ''}`);
};

(async () => {
  const child = spawn(EDGE, [
    '--headless=new', '--disable-gpu', '--no-sandbox',
    `--remote-debugging-port=${PORT}`,
    '--user-data-dir=' + process.env.TEMP + '\\edge-cdp-scan',
    '--window-size=1500,950', scan_url,
  ], { stdio: 'ignore' });

  let page = null;
  for (let i = 0; i < 40 && !page; i++) {
    await sleep(500);
    try { page = (await getJson('/json/list')).find(t => t.type === 'page' && t.webSocketDebuggerUrl); } catch (_) {}
  }
  if (!page) { console.log('连不上'); child.kill(); process.exit(1); }

  const ws = new MiniWS(page.webSocketDebuggerUrl);
  await ws.ready;
  let id = 0; const pending = new Map(); const errors = [];
  ws.onMessage(t => {
    const m = JSON.parse(t);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m.result); pending.delete(m.id); return; }
    if (m.method === 'Runtime.exceptionThrown') {
      errors.push(m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text);
    }
  });
  const send = (method, params = {}) => new Promise(res => {
    const mid = ++id; pending.set(mid, res);
    ws.send(JSON.stringify({ id: mid, method, params }));
  });
  const ev = async expr => {
    const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) return '异常: ' + (r.exceptionDetails.exception?.description || r.exceptionDetails.text);
    return r.result?.value;
  };
  const J = async expr => JSON.parse(await ev('JSON.stringify(' + expr + ')'));

  await send('Runtime.enable');
  await ev('localStorage.clear()');

  // 等全品种名单 + K 线
  let n = 0;
  for (let i = 0; i < 30; i++) {
    await sleep(1500);
    n = await ev('scan.rows.length');
    if (typeof n === 'number' && n > 400) break;
    if (i === 4) await ev('loadScan(true)');
  }
  let kl = 0;
  for (let i = 0; i < 20; i++) {
    await sleep(1500);
    kl = await ev('diag.klines');
    if (typeof kl === 'number' && kl > 100) break;
    if (i === 5) await ev('loadKlines()');
  }

  console.log('\n=== 页面身份 ===');
  check('是扫盘模式（SCAN=true）', (await ev('SCAN')) === true);
  check('窗口标题以「行情图表」开头（保证浏览器窗口能被复用）',
    String(await ev('document.title')).indexOf('行情图表') === 0, String(await ev('document.title')));
  check('K 线已加载', kl > 100, `${kl} 根`);

  console.log('\n=== 全品种名单 ===');
  check('★ 名单是全市场的（>400 个）', n > 400, `${n} 个`);
  const cats = await J(`(function(){
    var c={}; scan.rows.forEach(function(r){ c[r.cat]=(c[r.cat]||0)+1; }); return c; })()`);
  console.log('   分类统计:', JSON.stringify(cats));
  check('★ 有股票合约', (cats['股票'] || 0) > 50, `${cats['股票'] || 0} 个`);
  check('★ 有黄金合约（XAU）', (cats['黄金'] || 0) >= 1);
  check('★ 有原油/商品合约（CL/BZ）', (cats['商品'] || 0) >= 1, `${cats['商品'] || 0} 个`);
  check('★ 加密币也在里面', (cats['加密'] || 0) > 300, `${cats['加密'] || 0} 个`);
  check('列表已渲染出行', (await ev(`document.querySelectorAll('#groups .it').length`)) > 400);
  check('按名字 A→Z 排（0G 在最前、中文币在最后）',
    (await J(`scan.view.slice(0,3).map(function(r){return r.base})`)).join(',') === '0G,1000000MOG,1000BONK'
    && /[\u4e00-\u9fa5]/.test((await J(`scan.view.slice(-3).map(function(r){return r.base})`)).join('')),
    JSON.stringify(await J(`scan.view.slice(0,3).map(function(r){return r.base})`)));
  check('列表里能看到「黄金/股票」标签',
    (await ev(`document.querySelectorAll('#groups .tag').length`)) > 20,
    `${await ev(`document.querySelectorAll('#groups .tag').length`)} 个标签`);

  console.log('\n=== 分类筛选 ===');
  check('筛选胶囊齐全（含 ♥ 收藏）', (await ev(`document.querySelectorAll('#scancats .chip').length`)) === 7,
    JSON.stringify(await J(`Array.prototype.map.call(document.querySelectorAll('#scancats .chip'),function(c){return c.textContent})`)));
  // 按 data-cat 点（比按文字稳，不怕以后改文案）
  const clickChip = async cat => {
    const ok = await ev(`(function(){var cs=document.querySelectorAll('#scancats .chip');
      for(var i=0;i<cs.length;i++){ if(cs[i].getAttribute('data-cat')==='${cat}'){ cs[i].click(); return true; } }
      return false; })()`);
    await sleep(500);
    return ok;
  };
  check('点到「股票」胶囊', (await clickChip('股票')) === true);
  check('只剩非加密（全是股票）',
    (await ev(`scan.view.length > 0 && scan.view.every(function(r){return r.kind!=='crypto'})`)) === true,
    `${await ev('scan.view.length')} 个`);
  check('点到「贵金属」胶囊', (await clickChip('黄金')) === true);
  check('只剩黄金/白银',
    (await ev(`scan.view.length > 0 && scan.view.every(function(r){return r.cat==='黄金'||r.cat==='白银'})`)) === true,
    JSON.stringify(await J(`scan.view.map(function(r){return r.base})`)));
  check('点「原油/商品」能筛出 CL/BZ', (await clickChip('商品')) === true
    && (await ev(`scan.view.length > 0`)) === true,
    JSON.stringify(await J(`scan.view.map(function(r){return r.base})`)));
  check('点回「全部」恢复全量', (await clickChip('all')) === true
    && (await ev('scan.view.length')) === n, `${await ev('scan.view.length')} 个`);

  console.log('\n=== 搜索筛选 ===');
  await ev(`(function(){var q=document.getElementById('scanq'); q.value='XAU';
            q.dispatchEvent(new Event('input')); return true; })()`);
  await sleep(400);
  const hit = await J(`scan.view.map(function(r){return r.base})`);
  check('搜 XAU 能搜到黄金', hit.length >= 1 && hit.join(',').indexOf('XAU') >= 0, JSON.stringify(hit));
  await ev(`(function(){var q=document.getElementById('scanq'); q.value='TSLA';
            q.dispatchEvent(new Event('input')); return true; })()`);
  await sleep(400);
  check('搜 TSLA 能搜到股票', (await J(`scan.view.map(function(r){return r.base})`)).join(',') === 'TSLA',
    JSON.stringify(await J(`scan.view.map(function(r){return r.base})`)));
  await ev(`(function(){var q=document.getElementById('scanq'); q.value='';
            q.dispatchEvent(new Event('input')); document.getElementById('groups').focus();
            return true; })()`);
  await sleep(300);

  console.log('\n=== ★↑↓ 快速切下一个（扫盘的核心）===');
  const key = async (k, code, vk) => {
    await send('Input.dispatchKeyEvent', { type: 'keyDown', key: k, code: code, windowsVirtualKeyCode: vk });
    await send('Input.dispatchKeyEvent', { type: 'keyUp', key: k, code: code, windowsVirtualKeyCode: vk });
    await sleep(700);
  };
  await ev(`scanSelect(scan.view[0].base, false)`);
  await sleep(300);
  const first = await ev('scan.sel');
  await key('ArrowDown', 'ArrowDown', 40);
  const second = await ev('scan.sel');
  check('↓ 切到了下一个品种', second !== first && !!second, `${first} -> ${second}`);
  check('图表跟着换了（#sym 同步）',
    String(await ev(`document.getElementById('sym').textContent`)) === second,
    `${await ev(`document.getElementById('sym').textContent`)}`);
  // ⚠️ 别只看 diag.klines>100 —— 那还是上一个品种的数据（踩过：见交接文档坑 38）。
  //    要等 dataKey 真的变成"新品种|周期"。
  let keyOk = false;
  for (let i = 0; i < 10; i++) {
    await sleep(1000);
    keyOk = String(await ev('dataKey')) === second + '|' + (await ev('iv'));
    if (keyOk) break;
  }
  check('新品种的 K 线真的换过来了', keyOk, `dataKey=${await ev('dataKey')}`);
  check('列表高亮跟着走', (await ev('scan.sel')) === second);
  const visible = await ev(`(function(){
    var box=document.getElementById('groups'), el=box.querySelector('.it.cur');
    if(!el) return 'no-cur';
    var b=box.getBoundingClientRect(), r=el.getBoundingClientRect();
    return (r.top >= b.top - 2 && r.bottom <= b.bottom + 2) ? 'in' : 'out';
  })()`);
  check('★ 选中行自动滚到可见区域（扫盘才不会跟丢）', visible === 'in', visible);

  await key('ArrowDown', 'ArrowDown', 40);
  await key('ArrowDown', 'ArrowDown', 40);
  const fourth = await ev('scan.sel');
  check('连按 ↓ 一路往下走', fourth !== second, `${second} -> ${fourth}`);
  const beforeUp = await ev('scan.sel');
  const idxBefore = await ev(`scanIdx('${beforeUp}')`);
  await key('ArrowUp', 'ArrowUp', 38);
  const back = await ev('scan.sel');
  check('↑ 正好退回上一行', back !== beforeUp
    && (await ev('scanIdx(scan.sel)')) === (idxBefore - 1),
    `第 ${idxBefore + 1} 行 -> ${back}（第 ${(await ev('scanIdx(scan.sel)')) + 1} 行）`);

  await key('PageDown', 'PageDown', 34);
  const pg = await ev('scanIdx(scan.sel)');
  check('PageDown 一次跳 10 个', pg >= 10, `现在第 ${pg + 1} 行`);

  console.log('\n=== 跳到黄金/股票看 K 线 ===');
  await ev(`scanSelect('XAU', false); scanPick('XAU')`);
  let goldKey = false;
  for (let i = 0; i < 12; i++) {
    await sleep(1000);
    goldKey = String(await ev('dataKey')) === 'XAU|' + (await ev('iv'));
    if (goldKey) break;
  }
  check('★ 黄金合约（XAUUSDT）K 线真的换过来了', goldKey, `dataKey=${await ev('dataKey')}`);
  const goldPx = Number(String(await ev(`document.getElementById('px').textContent`)).replace(/,/g, ''));
  check('★ 图表现价有值（XAU 是几千美元量级）', goldPx > 0 && goldKey, `#px=${goldPx}`);

  console.log('\n=== ♥ 收藏 + TradingView ===');
  await ev(`scan.cat='all'; scan.q=''; scanFilter(); paintScan();`);
  await ev(`fetch('/api/fav?base=XAU&on=0')`);      // 先清干净
  await sleep(500);
  await ev(`loadScan(true)`);
  await sleep(1500);
  const fav0 = await ev('scan.favs.length');
  await ev(`scanToggleFav('XAU')`);
  await sleep(700);
  check('点 ♥ 收藏成功（服务端也记下了）',
    (await ev('scan.favs.length')) === fav0 + 1 && (await ev(`scanIsFav('XAU')`)) === true,
    JSON.stringify(await J('scan.favs')));
  check('列表里出现实心 ♥', (await ev(`document.querySelectorAll('#groups .fav.on').length`)) >= 1,
    `${await ev(`document.querySelectorAll('#groups .fav.on').length`)} 个`);
  check('♥ 收藏 胶囊上显示数量',
    String(await ev(`document.querySelector('#scancats .chip[data-cat="fav"]').textContent`))
      .indexOf('1') >= 0,
    String(await ev(`document.querySelector('#scancats .chip[data-cat="fav"]').textContent`)));
  // 收藏筛选
  await ev(`scan.cat='fav'; scanFilter(); paintScan();`);
  await sleep(300);
  check('切到「♥ 收藏」只看到收藏的',
    (await ev(`scan.view.every(function(r){return scanIsFav(r.base)})`)) === true
    && (await ev('scan.view.length')) >= 1,
    `${await ev('scan.view.length')} 个: ${JSON.stringify(await J(`scan.view.map(function(r){return r.base})`))}`);
  // 取消收藏
  await ev(`scanToggleFav('XAU')`);
  await sleep(700);
  check('再点一次 = 取消收藏', (await ev(`scanIsFav('XAU')`)) === false,
    JSON.stringify(await J('scan.favs')));
  await ev(`scan.cat='all'; scanFilter(); paintScan();`);
  await sleep(200);

  console.log('\n=== 回归 ===');
  check('趋势线模块还在（这一页也能画线）', (await ev('typeof tl')) === 'object');
  check('周期按钮还能用', (await ev(`document.querySelectorAll('#periods a').length`)) === 7);
  check('页面无未捕获异常', errors.length === 0, errors.slice(0, 3).join(' | '));

  ws.close(); child.kill();
  console.log(`\n${passed}/${total} 项通过`);
  process.exit(passed === total ? 0 : 1);
})();
