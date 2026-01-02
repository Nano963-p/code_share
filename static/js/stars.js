
/* =========================================================
   Animated Stars Background (Canvas)
   ========================================================= */
(function () {
  const canvas = document.getElementById("stars-canvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d", { alpha: true });

  let w = 0, h = 0, dpr = 1;
  const STAR_COUNT = 240;
  const stars = [];
  let mouseX = 0, mouseY = 0;

  function resize() {
    dpr = Math.max(1, Math.min(2, window.devicePixelRatio || 1));
    w = window.innerWidth;
    h = window.innerHeight;
    canvas.style.width = w + "px";
    canvas.style.height = h + "px";
    canvas.width = Math.floor(w * dpr);
    canvas.height = Math.floor(h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function rand(min, max) { return Math.random() * (max - min) + min; }

  function initStars() {
    stars.length = 0;
    for (let i = 0; i < STAR_COUNT; i++) {
      stars.push({
        x: rand(0, w),
        y: rand(0, h),
        r: rand(0.6, 1.8),
        vx: rand(-0.18, 0.30),
        vy: rand(-0.12, 0.22),
        tw: rand(0.001, 0.006),
        ph: rand(0, Math.PI * 2),
        a: rand(0.25, 0.95)
      });
    }
  }

  function drawBackground() {
    const g = ctx.createRadialGradient(w * 0.35, h * 0.35, 80, w * 0.5, h * 0.5, Math.max(w, h));
    g.addColorStop(0, "rgba(120, 60, 200, 0.25)");
    g.addColorStop(0.5, "rgba(35, 16, 80, 0.65)");
    g.addColorStop(1, "rgba(10, 6, 24, 1)");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, w, h);
  }

  function animate() {
    ctx.clearRect(0, 0, w, h);
    drawBackground();

    const px = (mouseX - w / 2) * 0.003;
    const py = (mouseY - h / 2) * 0.003;

    for (let i = 0; i < stars.length; i++) {
      const s = stars[i];
      s.x += s.vx; s.y += s.vy;

      if (s.x < -20) s.x = w + 20;
      if (s.x > w + 20) s.x = -20;
      if (s.y < -20) s.y = h + 20;
      if (s.y > h + 20) s.y = -20;

      s.ph += s.tw * 60;
      const twinkle = 0.55 + 0.45 * Math.sin(s.ph);
      const alpha = s.a * twinkle;

      ctx.beginPath();
      ctx.fillStyle = `rgba(220, 210, 255, ${alpha})`;
      ctx.arc(s.x + px, s.y + py, s.r, 0, Math.PI * 2);
      ctx.fill();
    }
    requestAnimationFrame(animate);
  }

  window.addEventListener("resize", () => { resize(); initStars(); });
  window.addEventListener("mousemove", (e) => { mouseX = e.clientX; mouseY = e.clientY; }, { passive: true });

  resize(); initStars(); animate();
})();


/* Shooting star (subtle) */
(function(){
  const canvas = document.getElementById("stars-canvas");
  if(!canvas) return;
  const ctx = canvas.getContext("2d");
  let w = window.innerWidth, h = window.innerHeight;
  function resize(){ w=window.innerWidth; h=window.innerHeight; }
  window.addEventListener("resize", resize);

  function shoot(){
    const startX = Math.random()*w*0.6;
    const startY = Math.random()*h*0.4;
    const len = 180 + Math.random()*220;
    const ang = Math.PI * (0.75 + Math.random()*0.08); // down-right
    const vx = Math.cos(ang)*18;
    const vy = Math.sin(ang)*18;
    let x=startX, y=startY, t=0;
    const alpha0 = 0.9;

    function step(){
      t++;
      x += vx;
      y += vy;
      ctx.save();
      ctx.globalCompositeOperation = "lighter";
      ctx.strokeStyle = `rgba(210,200,255,${Math.max(0, alpha0 - t/30)})`;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(x, y);
      ctx.lineTo(x - Math.cos(ang)*len, y - Math.sin(ang)*len);
      ctx.stroke();
      ctx.restore();
      if(t<30) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }
  setInterval(() => { if(Math.random()<0.6) shoot(); }, 3000);
})();
