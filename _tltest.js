// 趋势线测试（v0.16 重写版）：在真实浏览器里用真鼠标事件驱动，
// 验证「点两下成一条线 / 多条线 / 黏住 K 线 / 选中删除 / 撤销清空 / 持久化 / 画线时锁图表」。
const net = require('net');
const crypto = require('crypto');
const http = require('http');
const { spawn } = require('child_process');

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const PORT = 9336;
const target = process.argv[2];
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
  console.log(`  ${cond ? '✔' : '✗'} ${label}${extra ? '   ' + extra : ''}`);
};

(async () => {
  const child = spawn(EDGE, [
    '--headless=new', '--disable-gpu', '--no-sandbox',
    `--remote-debugging-port=${PORT}`,
    '--user-data-dir=' + process.env.TEMP + '\\edge-cdp-tl2',
    '--window-size=1400,900', target,
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
  await ev('localStorage.clear()');      // 从干净状态开始，别被上次测试的线干扰
  await ev('tl.loadedKey = null; loadTl();');
  await sleep(300);

  const click = async (x, y) => {
    for (const type of ['mousePressed', 'mouseReleased']) {
      await send('Input.dispatchMouseEvent', { type, x, y, button: 'left', clickCount: 1, buttons: type === 'mousePressed' ? 1 : 0 });
      await sleep(30);
    }
    await sleep(160);
  };
  const drag = async (x1, y1, x2, y2) => {
    await send('Input.dispatchMouseEvent', { type: 'mousePressed', x: x1, y: y1, button: 'left', clickCount: 1, buttons: 1 });
    await sleep(50);
    const steps = 10;
    for (let i = 1; i <= steps; i++) {
      await send('Input.dispatchMouseEvent', {
        type: 'mouseMoved', button: 'left', buttons: 1,
        x: x1 + (x2 - x1) * i / steps, y: y1 + (y2 - y1) * i / steps,
      });
      await sleep(25);
    }
    await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: x2, y: y2, button: 'left', clickCount: 1, buttons: 0 });
    await sleep(250);
  };

  // ---- 等 K 线 ----
  let klines = 0;
  for (let i = 0; i < 24; i++) {
    await sleep(2000);
    klines = await ev('diag.klines');
    if (typeof klines === 'number' && klines > 100) break;
    if (i === 6 || i === 14) await ev('loadKlines()');
  }
  const box = await J(`(function(){
    var c=document.getElementById('chart').getBoundingClientRect();
    return {x:c.left, y:c.top, w:c.width, h:c.height};
  })()`);
  console.log(`\n=== 前提 ===`);
  console.log(`  图表区 (${box.x|0},${box.y|0}) ${box.w|0}×${box.h|0}  品种=${await ev('cur')}  周期=${await ev('iv')}`);
  check('K 线已加载', klines > 100, `${klines} 根`);
  check('overlay 不吃鼠标事件', (await ev(`getComputedStyle(document.getElementById('overlay')).pointerEvents`)) === 'none');
  check('初始没有趋势线', (await ev('tl.lines.length')) === 0);
  check('初始「撤销」「清空」隐藏',
    (await ev(`getComputedStyle(document.getElementById('undo')).display`)) === 'none' &&
    (await ev(`getComputedStyle(document.getElementById('clr')).display`)) === 'none');

  const dbtn = await J(`(function(){var r=document.getElementById('draw').getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2}})()`);
  const P = (fx, fy) => ({ x: box.x + box.w * fx, y: box.y + box.h * fy });

  // ---- 画第一条：点两下 ----
  console.log('\n=== 画线：点两下成一条 ===');
  await click(dbtn.x, dbtn.y);
  check('进入画线模式', (await ev('tl.mode')) === true);
  check('按钮高亮', (await ev(`document.getElementById('draw').className`)) === 'on');
  let a = P(0.28, 0.66), b = P(0.60, 0.34);
  await click(a.x, a.y);
  check('第一下只落起点、还没成线',
    (await ev('tl.pending !== null')) === true && (await ev('tl.lines.length')) === 0);
  await click(b.x, b.y);
  let st = await J(`(function(){var l=tl.lines[0];return {n:tl.lines.length, mode:tl.mode, p1:l&&l.p1, p2:l&&l.p2}})()`);
  check('第二下成一条线', st.n === 1 && st.p1 && st.p2, `n=${st.n}`);
  check('★ 画完仍留在画线模式（可以接着画）', st.mode === true);
  check('两点价格不同（不是退化成一个点）', Math.abs(st.p2 - st.p1) > 1e-9);

  // ---- 接着画第二、第三条 ----
  console.log('\n=== 想画多少条就画多少条 ===');
  let c = P(0.30, 0.30), d = P(0.72, 0.60);
  await click(c.x, c.y); await click(d.x, d.y);
  let e = P(0.40, 0.20), f = P(0.80, 0.44);
  await click(e.x, e.y); await click(f.x, f.y);
  check('连着画出 3 条线', (await ev('tl.lines.length')) === 3, `${await ev('tl.lines.length')} 条`);
  check('顶栏显示条数', (await ev(`document.getElementById('tlcount').textContent`)) === '3 条');
  check('「撤销」「清空」出现了',
    (await ev(`getComputedStyle(document.getElementById('undo')).display`)) !== 'none' &&
    (await ev(`getComputedStyle(document.getElementById('clr')).display`)) !== 'none');

  // ---- Esc 退出画线 ----
  console.log('\n=== Esc 退出画线模式 ===');
  await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 });
  await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 });
  await sleep(200);
  check('Esc 退出画线模式', (await ev('tl.mode')) === false);
  check('线还在（Esc 不删线）', (await ev('tl.lines.length')) === 3);

  // ---- 线真的画出来了 ----
  const painted = () => ev(`(function(){
    var o=document.getElementById('overlay');
    var d=o.getContext('2d').getImageData(0,0,o.width,o.height).data;
    var n=0,sx=0,sy=0;
    for(var i=0;i<d.length;i+=4){ if(d[i+3]>0){ n++; sx+=(i/4)%o.width; sy+=Math.floor((i/4)/o.width); } }
    return n?{n:n,cx:sx/n,cy:sy/n}:{n:0};
  })()`);
  let p0 = await painted();
  check('overlay 上有绘制像素', p0.n > 500, `${p0.n} 个不透明像素`);

  // ---- ★ 核心：平移/缩放时线要黏住 K 线，不许"跟着屏幕跑" ----
  console.log('\n=== ★ 线黏在 K 线上（用户的核心抱怨）===');
  const anchorMid = async () => await J(`(function(){
    var g=tlPixOf(tl.lines[0]);
    return g?{x:(g.x1+g.x2)/2, y:(g.y1+g.y2)/2}:null;
  })()`);
  let m0 = await anchorMid();
  await ev('chart.timeScale().scrollToPosition(45, false)');
  await sleep(500);
  let m1 = await anchorMid();
  let p1 = await painted();
  const anchorDx = m1.x - m0.x, paintedDx = p1.cx - p0.cx;
  check('平移后线跟着数据一起移动（不是钉在屏幕上）',
    Math.abs(paintedDx - anchorDx) < 25 || p1.n === 0,
    `锚点移动 ${anchorDx.toFixed(1)}px，像素移动 ${paintedDx.toFixed(1)}px`);

  // 价格轴变了（自动缩放/拖价格轴）也要重画 —— 以前这里会"停在屏幕上不动"
  const stamped = () => J(`(function(){
    var o=document.getElementById('overlay');
    var d=o.getContext('2d').getImageData(0,0,o.width,o.height).data;
    var n=0,x0=1e9,y0=1e9,x1=-1e9,y1=-1e9;
    for(var y=0;y<o.height;y++)for(var x=0;x<o.width;x++){
      if(d[(y*o.width+x)*4+3]>0){n++;if(x<x0)x0=x;if(x>x1)x1=x;if(y<y0)y0=y;if(y>y1)y1=y;}
    }
    var g=tlPixOf(tl.lines[0]);
    return {n:n, x0:x0, y0:y0, x1:x1, y1:y1, g:g};
  })()`);
  await ev(`candleSeries.priceScale().applyOptions({autoScale:false, scaleMargins:{top:0.25,bottom:0.15}})`);
  await sleep(600);                       // 等看门狗（120ms 一轮）重画
  let sk = await stamped();
  // 判据：叠加层上画出来的包围盒必须**框得住**第一条线的两个端点。
  // 如果价格轴变了却没重画，端点会跑到包围盒外面去（线停在屏幕上不动）。
  let contain = true, tested = 0;
  if (sk.n > 0 && sk.g) {
    [[sk.g.x1, sk.g.y1], [sk.g.x2, sk.g.y2]].forEach(([px, py]) => {
      if (px < -20 || px > box.w + 20 || py < -20 || py > box.h + 20) return;
      tested++;
      if (!(px >= sk.x0 - 8 && px <= sk.x1 + 8 && py >= sk.y0 - 8 && py <= sk.y1 + 8)) contain = false;
    });
  }
  check('★ 价格轴变化后叠加层跟着重画（看门狗生效）', sk.n > 0 && tested > 0 && contain,
    `包围盒 (${sk.x0|0},${sk.y0|0})-(${sk.x1|0},${sk.y1|0})，检测端点 ${tested} 个`);
  check('三条线都还在', (await ev('tl.lines.length')) === 3);
  await ev(`candleSeries.priceScale().applyOptions({autoScale:true})`);
  await ev('chart.timeScale().fitContent()');
  await sleep(300);

  // ---- 拖端点只动那一条 ----
  console.log('\n=== 拖端点 ===');
  await ev('tl.sel = tl.lines[0].id; drawTrend()');
  let before = await J(`(function(){
    var l=tl.lines[0], o=tl.lines[1];
    return {p1:l.p1, p2:l.p2, other:o.p1, g:tlPixOf(l)};
  })()`);
  await drag(box.x + before.g.x2, box.y + before.g.y2, box.x + before.g.x2 + 110, box.y + before.g.y2 + 50);
  let after = await J(`(function(){
    var l=tl.lines[0], o=tl.lines[1];
    return {p1:l.p1, p2:l.p2, other:o.p1};
  })()`);
  check('拖终点改变了这一条的价格', Math.abs(after.p2 - before.p2) > 1e-9,
    `${before.p2.toFixed(4)} -> ${after.p2.toFixed(4)}`);
  check('别的线没被带着改', Math.abs(after.other - before.other) < 1e-12);

  // ---- 画线模式必须锁住图表（对照组：不锁的时候拖动一定会平移）----
  console.log('\n=== 画线时图表纹丝不动（★ 用户明说过"画面跟着手跑"）===');
  const range = async () => await J(`(function(){var r=chart.timeScale().getVisibleLogicalRange();return r?{from:r.from,to:r.to}:null})()`);
  await ev('chart.timeScale().scrollToPosition(40, false)');   // 先造出"两边都能挪"的状态
  await sleep(300);
  let r0 = await range();
  await drag(box.x + box.w * 0.5, box.y + box.h * 0.5, box.x + box.w * 0.2, box.y + box.h * 0.5);
  let r1 = await range();
  check('对照：非画线模式拖动**能**平移图表', Math.abs(r1.from - r0.from) > 1,
    `from ${r0.from.toFixed(1)} -> ${r1.from.toFixed(1)}`);

  await click(dbtn.x, dbtn.y);            // 进画线模式
  await ev('chart.timeScale().scrollToPosition(40, false)');
  await sleep(300);
  let r2 = await range();
  const nBeforeDrag = await ev('tl.lines.length');
  await drag(box.x + box.w * 0.5, box.y + box.h * 0.5, box.x + box.w * 0.2, box.y + box.h * 0.5);
  let r3 = await range();
  check('★ 画线模式里拖动图表不动（已锁）', Math.abs(r3.from - r2.from) < 0.01,
    `from ${r2.from.toFixed(3)} -> ${r3.from.toFixed(3)}`);
  // 顺带：画线模式里"按住拖一下"本来就该成一条线（TradingView 手感）
  check('这一次拖动顺便画出一条线（拖拽画线手感）',
    (await ev('tl.lines.length')) === nBeforeDrag + 1,
    `${nBeforeDrag} -> ${await ev('tl.lines.length')}`);
  await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 });
  await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 });
  await sleep(150);
  await ev('chart.timeScale().fitContent()');
  await sleep(200);

  // ---- 30 秒自动刷新不该把视角拽回去 ----
  console.log('\n=== 后台刷新不重置视角 ===');
  await ev('chart.timeScale().scrollToPosition(60, false)');
  await sleep(300);
  let rv0 = await range();
  await ev('loadKlines()');
  await sleep(1200);
  let rv1 = await range();
  check('同一品种/周期再拉一次 K 线，视角保持不变',
    Math.abs(rv1.from - rv0.from) < 3, `from ${rv0.from.toFixed(1)} -> ${rv1.from.toFixed(1)}`);

  // ---- 选中 + Delete 删除一条 ----
  console.log('\n=== 选中一条删掉它 ===');
  const n0 = await ev('tl.lines.length');
  let mid = await J(`(function(){
    var l=tl.lines[tl.lines.length-1], g=tlPixOf(l);
    return g?{x:(g.x1+g.x2)/2, y:(g.y1+g.y2)/2, id:l.id}:null;
  })()`);
  await click(box.x + mid.x, box.y + mid.y);
  check('点一下线 = 选中它', (await ev('tl.sel')) === mid.id, `sel=${await ev('tl.sel')} id=${mid.id}`);
  await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Delete', code: 'Delete', windowsVirtualKeyCode: 46 });
  await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Delete', code: 'Delete', windowsVirtualKeyCode: 46 });
  await sleep(200);
  // 用相对条数断言：这段之前"画线模式里拖一下"会顺带多画一条，
  // 写死绝对条数就成了测试自己的问题（真实教训，见交接文档坑 37）
  check('Delete 删掉了选中那一条', (await ev('tl.lines.length')) === n0 - 1,
    `${n0} -> ${await ev('tl.lines.length')}`);

  // ---- 撤销 / 清空 ----
  console.log('\n=== 撤销 / 清空 ===');
  const n1 = await ev('tl.lines.length');
  const ubtn = await J(`(function(){var r=document.getElementById('undo').getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2}})()`);
  await click(ubtn.x, ubtn.y);
  check('「撤销」删掉最后一条', (await ev('tl.lines.length')) === n1 - 1,
    `${n1} -> ${await ev('tl.lines.length')}`);
  const cbtn = await J(`(function(){var r=document.getElementById('clr').getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2}})()`);
  await click(cbtn.x, cbtn.y);
  check('「清空」全删', (await ev('tl.lines.length')) === 0);
  check('清空后 localStorage 也清了', (await ev(`localStorage.getItem(tlKey())`)) === null);

  // ---- 持久化 + 切周期隔离 + 老格式兼容 ----
  console.log('\n=== 持久化 / 切周期 / 老格式兼容 ===');
  await click(dbtn.x, dbtn.y);
  await click(a.x, a.y); await click(b.x, b.y);
  const lsKey = await ev('tlKey()');
  const stored = await J(`JSON.parse(localStorage.getItem(tlKey())||'[]')`);
  check('写进了 localStorage 且是数组', Array.isArray(stored) && stored.length === 1, `key=${lsKey}`);
  check('存的是时间+价格（不是屏幕坐标）',
    stored[0] && stored[0].t1 !== undefined && stored[0].p1 !== undefined);
  await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 });
  await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 });
  await sleep(150);

  // 等某个周期的新数据真的到位（只看 diag.klines>100 会被上一个周期的数据骗到）
  const waitData = async want => {
    for (let i = 0; i < 20; i++) {
      await sleep(1500);
      const dk = await ev('dataKey');
      if (dk === (await ev('cur')) + '|' + want && (await ev('diag.klines')) > 100) return true;
    }
    return false;
  };

  await ev(`setInterval_('4h')`);
  const ok4 = await waitData('4h');
  check('切到 4h 成功', (await ev('iv')) === '4h' && ok4, `K线=${await ev('diag.klines')} 根`);
  check('4h 是另一份趋势线（不串）', (await ev('tl.lines.length')) === 0,
    `${await ev('tl.lines.length')} 条`);
  await ev(`setInterval_('1h')`);
  const ok1 = await waitData('1h');
  check('切回 1h 拉到了数据', ok1);
  check('切回 1h，线还在', (await ev('tl.lines.length')) === 1, `${await ev('tl.lines.length')} 条`);

  // 老版本存的是 [{time,price},{time,price}]，换格式不能让用户的线凭空消失
  await ev(`localStorage.setItem(tlKey(), JSON.stringify([{time:1700000000,price:100},{time:1700100000,price:120}]))`);
  await ev(`tl.loadedKey = null; loadTl();`);
  const mig = await J(`(function(){var l=tl.lines[0];return {n:tl.lines.length,p1:l&&l.p1,p2:l&&l.p2}})()`);
  check('能读老格式（单条 → 数组）', mig.n === 1 && mig.p1 === 100 && mig.p2 === 120, JSON.stringify(mig));

  // ---- 回归 ----
  console.log('\n=== 回归 ===');
  await ev('localStorage.clear(); tl.loadedKey=null; loadTl();');
  check('K 线仍是 500 根', (await ev('diag.klines')) === 500);
  check('缩放/拖动仍可用（timeScale 有 API）',
    (await ev(`typeof chart.timeScale().scrollToRealTime === 'function'`)) === true);
  check('页面无未捕获异常', errors.length === 0, errors.slice(0, 3).join(' | '));

  ws.close(); child.kill();
  console.log(`\n${passed}/${total} 项通过`);
  process.exit(passed === total ? 0 : 1);
})();
