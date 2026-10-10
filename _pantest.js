// 测「画线时图表会不会跟着动」。
// 这是用户报的问题：按下拖动时图表跟着平移，线画不准。
const net = require('net'), crypto = require('crypto'), http = require('http');
const { spawn } = require('child_process');
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const PORT = 9343, target = process.argv[2];
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
    `--remote-debugging-port=${PORT}`, '--user-data-dir=' + process.env.TEMP + '\\edge-cdp-pan',
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

  // 用「可视时间范围」判断图表有没有被平移/缩放
  const range = async () => JSON.parse(await ev(`JSON.stringify(chart.timeScale().getVisibleLogicalRange())`));
  const click = async (x, y) => {
    await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y, buttons: 0 }); await sleep(60);
    await send('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', clickCount: 1, buttons: 1 }); await sleep(40);
    await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', clickCount: 1, buttons: 0 }); await sleep(200); };
  const drag = async (x1, y1, x2, y2, steps = 10) => {
    await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: x1, y: y1, buttons: 0 }); await sleep(60);
    await send('Input.dispatchMouseEvent', { type: 'mousePressed', x: x1, y: y1, button: 'left', clickCount: 1, buttons: 1 }); await sleep(50);
    for (let i = 1; i <= steps; i++) {
      await send('Input.dispatchMouseEvent', { type: 'mouseMoved', button: 'left', buttons: 1,
        x: x1 + (x2 - x1) * i / steps, y: y1 + (y2 - y1) * i / steps });
      await sleep(35);
    }
    await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: x2, y: y2, button: 'left', clickCount: 1, buttons: 0 });
    await sleep(250); };

  // ⚠️ fitContent() 之后可视区间正好等于数据区间，两边都没有可平移的空间，
  // 拖了也看不出变化。所以先滚到中间，造出"左右都能挪"的状态再测。
  const makePannable = async () => {
    await ev(`chart.timeScale().scrollToPosition(40, false)`);
    await sleep(250);
  };

  console.log('\n=== 前提：非画线模式下拖动应当能平移图表（对照组） ===');
  await makePannable();
  let r0 = await range();
  await drag(box.x + box.w * 0.5, box.y + box.h * 0.5, box.x + box.w * 0.3, box.y + box.h * 0.5);
  let r1 = await range();
  check('对照：非画线模式拖动 → 图表确实平移了',
    Math.abs(r1.from - r0.from) > 1, `from ${r0.from.toFixed(1)} -> ${r1.from.toFixed(1)}`);

  console.log('\n=== 正题：画线模式下拖动，图表必须纹丝不动 ===');
  await ev(`localStorage.clear(); tl.loadedKey=null; loadTl(); 'ready'`);
  await sleep(300);
  await makePannable();
  await click(dbtn.x, dbtn.y);
  check('已进入画线模式', (await ev('tl.mode')) === true);

  const before = await range();
  await drag(box.x + box.w * 0.35, box.y + box.h * 0.60, box.x + box.w * 0.65, box.y + box.h * 0.30);
  const after = await range();
  check('画线模式下拖动：图表**没有**平移',
    Math.abs(after.from - before.from) < 0.5 && Math.abs(after.to - before.to) < 0.5,
    `from ${before.from.toFixed(1)}->${after.from.toFixed(1)}, to ${before.to.toFixed(1)}->${after.to.toFixed(1)}`);

  const st = JSON.parse(await ev(`JSON.stringify({l:tl.lines[0],mode:tl.mode,n:tl.lines.length})`));
  check('一次按下-拖动-抬起就画出了一条线', st.n === 1 && st.l,
    `p1=${st.l ? st.l.p1.toFixed(1) : null}, p2=${st.l ? st.l.p2.toFixed(1) : null}`);
  check('画完仍在画线模式（用户要连着画）', st.mode === true);

  const pix = await ev(`(function(){
    var o=document.getElementById('overlay');
    var d=o.getContext('2d').getImageData(0,0,o.width,o.height).data;
    var n=0; for(var i=3;i<d.length;i+=4) if(d[i]>0) n++; return n; })()`);
  check('线真的画在画布上', pix > 200, `${pix} 个不透明像素`);

  console.log('\n=== 再测「点两下」（不拖动）也要能画 ===');
  await ev(`localStorage.clear(); tl.loadedKey=null; loadTl(); 'reset'`);
  await sleep(200);
  await makePannable();
  await click(dbtn.x, dbtn.y);
  const b2 = await range();
  await click(box.x + box.w * 0.25, box.y + box.h * 0.70);
  const midState = JSON.parse(await ev(`JSON.stringify({pending:!!tl.pending})`));
  await click(box.x + box.w * 0.60, box.y + box.h * 0.35);
  const a2 = await range();
  const st2 = JSON.parse(await ev(`JSON.stringify({n:tl.lines.length})`));
  check('第一下落下起点', midState.pending === true);
  check('第二下画出线', st2.n === 1);
  check('点两下期间图表也没动',
    Math.abs(a2.from - b2.from) < 0.5, `from ${b2.from.toFixed(1)}->${a2.from.toFixed(1)}`);

  console.log('\n=== 退出画线后，拖动要恢复正常（不能一直锁着）===');
  await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 });
  await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 });
  await sleep(200);
  check('Esc 退出画线模式', (await ev('tl.mode')) === false);
  await makePannable();
  const r2 = await range();
  await drag(box.x + box.w * 0.5, box.y + box.h * 0.5, box.x + box.w * 0.25, box.y + box.h * 0.5);
  const r3 = await range();
  check('退出后拖动 → 图表又能平移了',
    Math.abs(r3.from - r2.from) > 1, `from ${r2.from.toFixed(1)} -> ${r3.from.toFixed(1)}`);

  console.log('\n=== 拖已画好的线：图表不许跟着一起动 ===');
  const gm = JSON.parse(await ev(`JSON.stringify((function(){
    var g=tlPixOf(tl.lines[0]);
    return g?{x:(g.x1+g.x2)/2, y:(g.y1+g.y2)/2}:null})())`));
  if (gm) {
    await makePannable();
    const r4 = await range();
    await drag(box.x + gm.x, box.y + gm.y, box.x + gm.x, box.y + gm.y - 80);
    const r5 = await range();
    check('拖线身时图表不动（线被拖走了，画面没动）',
      Math.abs(r5.from - r4.from) < 0.5, `from ${r4.from.toFixed(1)} -> ${r5.from.toFixed(1)}`);
  } else {
    check('取到第一条线的位置', false);
  }

  ws.close(); child.kill();
  console.log('\n' + passed + '/' + total + ' 项通过');
  process.exit(passed === total ? 0 : 1);
})();