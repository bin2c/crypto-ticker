// 决定性实验：真实用户序列「画一条 → 清除 → 再画一条」能不能走通？
// 这个序列能过 = 产品没问题，pantest 最后一段失败是测试脚本的残留状态。
const net = require('net'), crypto = require('crypto'), http = require('http');
const { spawn } = require('child_process');
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const PORT = 9348, target = process.argv[2];
const sleep = ms => new Promise(r => setTimeout(r, ms));
const getJson = p => new Promise((res, rej) => {
  http.get({ host: '127.0.0.1', port: PORT, path: p }, r => {
    let b = ''; r.on('data', d => (b += d));
    r.on('end', () => { try { res(JSON.parse(b)); } catch (e) { rej(e); } });
  }).on('error', rej);
});
class MiniWS {
  constructor(url) {
    const u = new URL(url); this.buf = Buffer.alloc(0); this.handlers = [];
    this.sock = net.connect(Number(u.port), u.hostname);
    this.ready = new Promise((resolve, reject) => {
      const key = crypto.randomBytes(16).toString('base64');
      this.sock.on('connect', () => this.sock.write(
        `GET ${u.pathname}${u.search} HTTP/1.1\r\nHost: ${u.host}\r\nUpgrade: websocket\r\n` +
        `Connection: Upgrade\r\nSec-WebSocket-Key: ${key}\r\nSec-WebSocket-Version: 13\r\n\r\n`));
      this.sock.on('error', reject);
      let hs = false;
      this.sock.on('data', c => { this.buf = Buffer.concat([this.buf, c]);
        if (!hs) { const i = this.buf.indexOf('\r\n\r\n'); if (i < 0) return;
          hs = true; this.buf = this.buf.subarray(i + 4); resolve(); } this._drain(); });
    });
  }
  _drain() { for (;;) { const b = this.buf; if (b.length < 2) return;
    const op = b[0] & 0x0f; let len = b[1] & 0x7f, off = 2;
    if (len === 126) { if (b.length < 4) return; len = b.readUInt16BE(2); off = 4; }
    else if (len === 127) { if (b.length < 10) return; len = Number(b.readBigUInt64BE(2)); off = 10; }
    if (b.length < off + len) return;
    const p = b.subarray(off, off + len); this.buf = b.subarray(off + len);
    if (op === 1) this.handlers.forEach(h => h(p.toString('utf8'))); else if (op === 8) { this.sock.end(); return; } } }
  onMessage(f) { this.handlers.push(f); }
  send(str) { const d = Buffer.from(str, 'utf8'), m = crypto.randomBytes(4); let h;
    if (d.length < 126) h = Buffer.from([0x81, 0x80 | d.length]);
    else if (d.length < 65536) { h = Buffer.alloc(4); h[0] = 0x81; h[1] = 0x80 | 126; h.writeUInt16BE(d.length, 2); }
    else { h = Buffer.alloc(10); h[0] = 0x81; h[1] = 0x80 | 127; h.writeBigUInt64BE(BigInt(d.length), 2); }
    const mm = Buffer.alloc(d.length); for (let i = 0; i < d.length; i++) mm[i] = d[i] ^ m[i % 4];
    this.sock.write(Buffer.concat([h, m, mm])); }
  close() { try { this.sock.destroy(); } catch (_) {} }
}
let passed = 0, total = 0;
const check = (l, c, e = '') => { total++; if (c) passed++; console.log(`  ${c ? '✔' : '✗'} ${l}${e ? '   ' + e : ''}`); };
(async () => {
  const child = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-sandbox',
    `--remote-debugging-port=${PORT}`, '--user-data-dir=' + process.env.TEMP + '\\edge-cdp-seq',
    '--window-size=1400,900', target], { stdio: 'ignore' });
  let page = null;
  for (let i = 0; i < 40 && !page; i++) { await sleep(500);
    try { page = (await getJson('/json/list')).find(t => t.type === 'page' && t.webSocketDebuggerUrl); } catch (_) {} }
  const ws = new MiniWS(page.webSocketDebuggerUrl); await ws.ready;
  let id = 0; const pending = new Map();
  ws.onMessage(t => { const m = JSON.parse(t);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m.result); pending.delete(m.id); } });
  const send = (method, params = {}) => new Promise(res => {
    const mid = ++id; pending.set(mid, res); ws.send(JSON.stringify({ id: mid, method, params })); });
  const ev = async e => { const r = await send('Runtime.evaluate', { expression: e, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) return '异常: ' + (r.exceptionDetails.exception?.description || r.exceptionDetails.text);
    return r.result?.value; };
  await send('Runtime.enable');
  let k = 0;
  for (let i = 0; i < 24; i++) { await sleep(2000); k = await ev('diag.klines') || 0; if (k > 100) break; await ev('loadKlines()'); }
  console.log(`K线 ${k} 根`);

  const box = JSON.parse(await ev(`JSON.stringify((function(){
    var c=document.getElementById('chart').getBoundingClientRect();
    return {x:c.left,y:c.top,w:c.width,h:c.height}})())`));
  const dbtn = JSON.parse(await ev(`JSON.stringify((function(){var r=document.getElementById('draw').getBoundingClientRect();return{x:r.left+r.width/2,y:r.top+r.height/2}})())`));
  const cbtn = async () => JSON.parse(await ev(`JSON.stringify((function(){var r=document.getElementById('clr').getBoundingClientRect();return{x:r.left+r.width/2,y:r.top+r.height/2}})())`));
  const click = async (x, y) => {
    await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y, buttons: 0 }); await sleep(70);
    await send('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', clickCount: 1, buttons: 1 }); await sleep(45);
    await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', clickCount: 1, buttons: 0 }); await sleep(220); };

  // 起始：彻底清干净（模拟"用户刚打开页面，没有线"）
  await ev(`localStorage.clear(); tl.loadedKey=null; loadTl(); 'clean'`);
  await sleep(300);

  console.log('\n=== 真实序列 1：点两下画第一条 ===');
  await click(dbtn.x, dbtn.y);
  check('进入画线模式', (await ev('tl.mode')) === true);
  await click(box.x + box.w * 0.25, box.y + box.h * 0.70);
  await click(box.x + box.w * 0.60, box.y + box.h * 0.35);
  check('第一条画出来了', (await ev('tl.lines.length')) === 1);
  check('已落盘', !!(await ev(`localStorage.getItem(tlKey())`)));
  check('画完仍留在画线模式（可以接着画）', (await ev('tl.mode')) === true);

  console.log('\n=== 真实序列 2：点「清空」 ===');
  const cb = await cbtn();
  await click(cb.x, cb.y);
  check('线没了', (await ev('tl.lines.length')) === 0);
  check('localStorage 也清了', (await ev(`localStorage.getItem(tlKey())`)) === null);

  console.log('\n=== 真实序列 3：清空之后再画第二条（这就是之前失败的那段）===');
  // 上一步清空后仍停在画线模式，直接画
  await click(box.x + box.w * 0.30, box.y + box.h * 0.55);
  const midP = await ev('!!tl.pending');
  check('第一下落下起点', midP === true);
  await click(box.x + box.w * 0.70, box.y + box.h * 0.35);
  const st = JSON.parse(await ev(`JSON.stringify({mode:tl.mode,n:tl.lines.length})`));
  check('第二条也画出来了', st.n === 1, JSON.stringify(st));
  await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 });
  await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 });
  await sleep(200);
  check('Esc 之后退出画线模式', (await ev('tl.mode')) === false);

  console.log('\n=== 真实序列 4：拖这条线 ===');
  const g = await ev(`(function(){var p=tlPixOf(tl.lines[0]); return p?JSON.stringify({x:(p.x1+p.x2)/2,y:(p.y1+p.y2)/2}):null})()`);
  if (g) {
    const gm = JSON.parse(g);
    const before = await ev('tl.lines[0].p1');
    await send('Input.dispatchMouseEvent', { type: 'mousePressed', x: box.x + gm.x, y: box.y + gm.y, button: 'left', clickCount: 1, buttons: 1 }); await sleep(50);
    for (let i = 1; i <= 8; i++) {
      await send('Input.dispatchMouseEvent', { type: 'mouseMoved', button: 'left', buttons: 1,
        x: box.x + gm.x, y: box.y + gm.y - i * 8 }); await sleep(35);
    }
    await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: box.x + gm.x, y: box.y + gm.y - 64, button: 'left', clickCount: 1, buttons: 0 });
    await sleep(250);
    const after = await ev('tl.lines[0].p1');
    check('线被拖动了', Math.abs(after - before) > 1e-9, `${before?.toFixed(1)} -> ${after?.toFixed(1)}`);
  } else {
    check('取到线的位置', false);
  }

  await ev(`localStorage.clear(); 'bye'`);
  ws.close(); child.kill();
  console.log(`\n${passed}/${total} 项通过`);
  process.exit(passed === total ? 0 : 1);
})();
