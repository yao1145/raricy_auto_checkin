// bg.js — 低开销科幻背景：漂移星野 + 鼠标轨道粒子 + 随机流星
// 星云旋转由 styles.css 的 CSS transform 完成（GPU 合成），
// 本脚本仅负责 canvas 粒子，DPR 封顶 2 且页面隐藏时暂停渲染以控制开销。
// 鼠标靠近时，粒子绕各自独立的轨道（半径/周期/圆心偏移均不同）
// 做圆周运动，形成"科技感"的环绕效果；偶尔划过流星，同样遵循低开销与暂停规则。
(function () {
  "use strict";
  const canvas = document.getElementById("space-bg");
  if (!canvas) return;

  const ctx = canvas.getContext("2d");
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);

  const COUNT = 500;           // 粒子数（DPR 封顶 2 + 隐藏暂停，控制开销）
  const LINK_DIST = 100;       // 鼠标连线半径（px）
  const INFLUENCE_RADIUS = 100; // 轨道影响半径（px）
  const MAX_METEORS = 3;       // 同屏流星数量上限（压低开销）

  let w = 0;
  let h = 0;
  let running = true;
  let time = 0;                // 累计运行秒数（驱动流星生成）
  let nextMeteor = 0;          // 下一次流星生成时刻（秒，基于 time 时钟）
  let lastTs = null;           // 上一帧 rAF 时间戳（ms）
  let mouse = { x: -9999, y: -9999 };
  const particles = [];
  const meteors = [];          // 活跃流星

  function resize() {
    w = window.innerWidth || canvas.clientWidth;
    h = window.innerHeight || canvas.clientHeight;
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function makeParticle() {
    const phase = Math.random() * Math.PI * 2; // 轨道初始相位 0–2π
    return {
      x: Math.random() * w,
      y: Math.random() * h,
      vx: (Math.random() - 0.5) * 0.14,
      vy: (Math.random() - 0.5) * 0.14,
      r: Math.random() * 1.2 + 0.4,        // 粒子半径 0.4–1.6px（大小各异）
      tw: Math.random() * Math.PI * 2,     // 闪烁相位
      ts: Math.random() * 0.02 + 0.005,    // 闪烁速度
      orbitR: Math.random() * 52 + 18,     // 轨道半径 18–70px
      period: Math.random() * 1.5 + 0.7,   // 轨道周期 0.7–2.2s
      phase: phase,                        // 轨道初始相位（保留原字段）
      angle: phase,                        // 累积轨道角：由 dt 推进，速度随鼠标距离变化
      offsetX: (Math.random() - 0.5) * 72, // 圆心相对鼠标的水平偏移 -36..36
      offsetY: (Math.random() - 0.5) * 72, // 圆心相对鼠标的垂直偏移 -36..36
    };
  }

  function init() {
    particles.length = 0;
    for (let i = 0; i < COUNT; i++) particles.push(makeParticle());
  }

  function step(dt = 0) {
    ctx.clearRect(0, 0, w, h);
    const link2 = LINK_DIST * LINK_DIST;
    const inf2 = INFLUENCE_RADIUS * INFLUENCE_RADIUS;

    for (let i = 0; i < particles.length; i++) {
      const p = particles[i];

      // 常规漂移
      p.x += p.vx;
      p.y += p.vy;
      p.tw += p.ts;

      // 边缘环绕
      if (p.x < -5) p.x = w + 5;
      else if (p.x > w + 5) p.x = -5;
      if (p.y < -5) p.y = h + 5;
      else if (p.y > h + 5) p.y = -5;

      // 轨道角：无论是否受鼠标影响，都按基速推进，保证相位连续、进出影响区无突变
      const baseRate = (Math.PI * 2) / p.period;
      p.angle += baseRate * dt;

      // 鼠标影响：按邻近度把位置混合到"轨道目标"，越近越贴合、边缘平滑过渡
      const dx = mouse.x - p.x;
      const dy = mouse.y - p.y;
      const d2 = dx * dx + dy * dy;
      if (d2 < inf2) {
        const dist = Math.sqrt(d2);
        const blend = 1 - dist / INFLUENCE_RADIUS; // 中心=1，边缘=0
        // 距鼠标越近，绕轨道越快：边缘 1× → 中心 2.5×（线性平滑）
        const boost = 1 + blend * 1.5;
        p.angle += baseRate * boost * dt;
        const ox = mouse.x + p.offsetX; // 每个粒子独立的圆心（相对鼠标偏移）
        const oy = mouse.y + p.offsetY;
        const tx = ox + p.orbitR * Math.cos(p.angle);
        const ty = oy + p.orbitR * Math.sin(p.angle);
        p.x += (tx - p.x) * blend;
        p.y += (ty - p.y) * blend;
      }

      // 绘制粒子
      const alpha = 0.32 + Math.sin(p.tw) * 0.26;
      ctx.beginPath();
      ctx.fillStyle = "rgba(148, 197, 255, " + alpha.toFixed(3) + ")";
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fill();

      // 与鼠标连线（邻近才绘制）
      if (d2 < link2) {
        const t = 1 - Math.sqrt(d2) / LINK_DIST;
        ctx.beginPath();
        ctx.strokeStyle = "rgba(56, 189, 248, " + (t * 0.5).toFixed(3) + ")";
        ctx.lineWidth = 0.6;
        ctx.moveTo(p.x, p.y);
        ctx.lineTo(mouse.x, mouse.y);
        ctx.stroke();
      }
    }

    // 流星（shooting star）：随机生成、斜向划过、寿命短、头部亮尾渐变
    if (dt > 0 && time >= nextMeteor && meteors.length < MAX_METEORS) {
      meteors.push({
        x: Math.random() * w,              // 顶部/边缘随机出现
        y: Math.random() * h * 0.3,
        vx: -(3 + Math.random() * 3),      // 向左 3–6 px/帧（再乘 dt*60）
        vy: 2 + Math.random() * 2,         // 向下 2–4 px/帧
        len: 80 + Math.random() * 60,      // 尾迹长度 80–140px
        life: 0,
        maxLife: 0.8 + Math.random() * 0.6 // 存活 0.8–1.4s
      });
      nextMeteor = time + 2 + Math.random() * 4; // 2–6 秒后下一条
    }

    for (let j = meteors.length - 1; j >= 0; j--) {
      const m = meteors[j];
      m.x += m.vx * dt * 60;
      m.y += m.vy * dt * 60;
      m.life += dt;

      // 移除：寿命耗尽或飞出画布
      if (
        m.life >= m.maxLife ||
        m.x < -m.len || m.x > w + m.len ||
        m.y < -m.len || m.y > h + m.len
      ) {
        meteors.splice(j, 1);
        continue;
      }

      const fade = 1 - m.life / m.maxLife; // 随寿命渐隐
      ctx.globalAlpha = fade;

      const grad = ctx.createLinearGradient(
        m.x, m.y,
        m.x - m.vx * m.len, m.y - m.vy * m.len
      );
      grad.addColorStop(0, "rgba(148, 197, 255, 0.9)"); // 头部亮
      grad.addColorStop(1, "rgba(148, 197, 255, 0)");   // 尾部淡出
      ctx.strokeStyle = grad;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(m.x, m.y);
      ctx.lineTo(m.x - m.vx * m.len, m.y - m.vy * m.len);
      ctx.stroke();

      // 头部亮点
      ctx.fillStyle = "rgba(255, 255, 255, 0.9)";
      ctx.beginPath();
      ctx.arc(m.x, m.y, 1.5, 0, Math.PI * 2);
      ctx.fill();

      ctx.globalAlpha = 1;
    }
  }

  function loop(ts) {
    if (!running) return;
    if (lastTs === null) lastTs = ts;
    const dt = Math.min((ts - lastTs) / 1000, 0.1); // 秒；封顶 0.1s 防异常跳变
    lastTs = ts;
    time += dt;
    step(dt);
    requestAnimationFrame(loop);
  }

  // canvas 设置了 pointer-events: none（styles.css），监听 canvas 收不到事件；
  // pointermove 会冒泡到 window，且 canvas 铺满视口（从 0,0 开始），
  // 所以直接用视口坐标 e.clientX/e.clientY 就是 canvas 坐标。
  window.addEventListener("pointermove", function (e) {
    mouse.x = e.clientX;
    mouse.y = e.clientY;
  });
  document.documentElement.addEventListener("pointerleave", function () {
    mouse.x = -9999;
    mouse.y = -9999;
  });

  document.addEventListener("visibilitychange", function () {
    if (document.hidden) {
      running = false;
    } else {
      running = true;
      lastTs = null; // 重置基准，避免把隐藏时长计入轨道时钟
      requestAnimationFrame(loop);
    }
  });

  window.addEventListener("resize", resize);

  resize();
  init();
  if (reduced) {
    step(); // 减少动态效果：仅绘制一帧静态星野
  } else {
    requestAnimationFrame(loop);
  }
})();
