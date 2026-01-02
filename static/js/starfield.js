(() => {
  const canvas = document.getElementById("starfield");
  if (!canvas) return;

  const ctx = canvas.getContext("2d", { alpha: true });

  let w = 0, h = 0, dpr = 1;

  function resize() {
    dpr = Math.max(1, window.devicePixelRatio || 1);
    w = window.innerWidth;
    h = window.innerHeight;
    canvas.width = Math.floor(w * dpr);
    canvas.height = Math.floor(h * dpr);
    canvas.style.width = w + "px";
    canvas.style.height = h + "px";
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  resize();
  window.addEventListener("resize", resize);

  const stars = [];
  const numStars = 220;
  const speed = 0.55;

  class Star {
    constructor() { this.reset(true); }
    reset(init = false) {
      this.x = Math.random() * w;
      this.y = Math.random() * h;
      this.z = Math.random() * w;
      this.size = 0.6 + Math.random() * 1.8;
      if (!init) this.z = w;
    }
    update() {
      this.z -= speed;
      if (this.z <= 1) this.reset(false);
    }
    draw() {
      const cx = w / 2;
      const cy = h / 2;

      const x = (this.x - cx) * (w / this.z) + cx;
      const y = (this.y - cy) * (w / this.z) + cy;

      const opacity = 1 - (this.z / w);
      const size = opacity * this.size * 3;

      ctx.beginPath();
      ctx.fillStyle = `rgba(255,255,255,${opacity})`;
      ctx.arc(x, y, size, 0, Math.PI * 2);
      ctx.fill();

      if (opacity > 0.70) {
        const g = ctx.createRadialGradient(x, y, 0, x, y, size * 3);
        g.addColorStop(0, `rgba(167,139,250,${opacity * 0.30})`);
        g.addColorStop(1, "rgba(167,139,250,0)");
        ctx.fillStyle = g;
        ctx.fillRect(x - size * 3, y - size * 3, size * 6, size * 6);
      }
    }
  }

  function init() {
    stars.length = 0;
    for (let i = 0; i < numStars; i++) stars.push(new Star());
  }

  init();

  function animate() {
    // trail effect
    ctx.fillStyle = "rgba(26, 11, 46, 0.20)";
    ctx.fillRect(0, 0, w, h);

    for (const s of stars) {
      s.update();
      s.draw();
    }
    requestAnimationFrame(animate);
  }

  animate();
})();
