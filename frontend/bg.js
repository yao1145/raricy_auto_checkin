// bg.js — 低开销科幻背景：漂移星野 + 鼠标联动粒子
// 星云旋转由 styles.css 的 CSS transform 完成（GPU 合成），
// 本脚本仅负责 canvas 粒子，粒子数保持低位，页面隐藏时暂停渲染。
(function () {
  "use strict";
  const canvas = document.getElementById("space-bg");
  if (!canvas) return;

  const ctx = canvas.getContext("2d");
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);

  const COUNT = 80;        // 粒子数（刻意压低以降低开销）
  const LINK_DIST = 150;   // 鼠标连线半径（px）

  let w = 0;
  let h = 0;
  let running = true;
  let mouse = { x: -9999, y: -9999 };
  const particles = [];

  function resize() {
    w = canvas.clientWidth;
    h = canvas.clientHeight;
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function makeParticle() {
    return {
      x: Math.random() * w,
      y: Math.random() * h,
      vx: (Math.random() - 0.5) * 0.14,
      vy: (Math.random() - 0.5) * 0.14,
      r: Math.random() * 1.2 + 0.4,
      tw: Math.random() * Math.PI * 2,     // 闪烁相位
      ts: Math.random() * 0.02 + 0.005,    // 闪烁速度
    };
  }

  function init() {
    particles.length = 0;
    for (let i = 0; i < COUNT; i++) particles.push(makeParticle());
  }

  function step() {
    ctx.clearRect(0, 0, w, h);
    const link2 = LINK_DIST * LINK_DIST;

    for (let i = 0; i < particles.length; i++) {
      const p = particles[i];
      p.x += p.vx;
      p.y += p.vy;
      p.tw += p.ts;

      // 边缘环绕
      if (p.x < -5) p.x = w + 5;
      else if (p.x > w + 5) p.x = -5;
      if (p.y < -5) p.y = h + 5;
      else if (p.y > h + 5) p.y = -5;

      const alpha = 0.32 + Math.sin(p.tw) * 0.26;
      ctx.beginPath();
      ctx.fillStyle = "rgba(148, 197, 255, " + alpha.toFixed(3) + ")";
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fill();

      // 与鼠标连线（邻近才绘制）
      const dx = mouse.x - p.x;
      const dy = mouse.y - p.y;
      const d2 = dx * dx + dy * dy;
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
  }

  function loop() {
    if (!running) return;
    step();
    requestAnimationFrame(loop);
  }

  canvas.addEventListener("pointermove", function (e) {
    const rect = canvas.getBoundingClientRect();
    mouse.x = e.clientX - rect.left;
    mouse.y = e.clientY - rect.top;
  });
  canvas.addEventListener("pointerleave", function () {
    mouse.x = -9999;
    mouse.y = -9999;
  });

  document.addEventListener("visibilitychange", function () {
    if (document.hidden) {
      running = false;
    } else {
      running = true;
      requestAnimationFrame(loop);
    }
  });

  window.addEventListener("resize", resize);

  resize();
  init();
  if (reduced) {
    step(); // 减少动态效果：仅绘制一帧静态星野
  } else {
    loop();
  }
})();
