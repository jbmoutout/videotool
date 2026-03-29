<script lang="ts">
  import { onDestroy } from "svelte";

  const W = 500;
  const H = 350;
  const SHIP_SIZE = 10;
  const TURN_SPEED = 0.07;
  const THRUST = 0.12;
  const FRICTION = 0.99;
  const BULLET_SPEED = 5;
  const BULLET_LIFE = 60;
  const ASTEROID_SPEED = 1.2;
  const SIZES = [20, 12, 7];

  interface Ship { x: number; y: number; angle: number; dx: number; dy: number }
  interface Bullet { x: number; y: number; dx: number; dy: number; life: number }
  interface Asteroid { x: number; y: number; dx: number; dy: number; size: number; verts: number[] }

  let canvas = $state<HTMLCanvasElement | null>(null);
  let animFrame = 0;
  let keys = new Set<string>();
  let ship: Ship = mkShip();
  let bullets: Bullet[] = [];
  let asteroids: Asteroid[] = [];
  let score = $state(0);
  let dead = $state(false);

  function mkShip(): Ship {
    return { x: W / 2, y: H / 2, angle: -Math.PI / 2, dx: 0, dy: 0 };
  }

  function mkVerts(size: number): number[] {
    const n = 8 + Math.floor(Math.random() * 5);
    return Array.from({ length: n }, () => size * (0.7 + Math.random() * 0.3));
  }

  function spawnAsteroid(x?: number, y?: number, si = 0): Asteroid {
    const size = SIZES[si];
    const a = Math.random() * Math.PI * 2;
    const spd = ASTEROID_SPEED * (1 + (2 - si) * 0.3) * (0.5 + Math.random() * 0.5);
    return {
      x: x ?? (Math.random() < 0.5 ? 0 : W),
      y: y ?? Math.random() * H,
      dx: Math.cos(a) * spd, dy: Math.sin(a) * spd,
      size, verts: mkVerts(size),
    };
  }

  function wrap(v: number, max: number) { return ((v % max) + max) % max; }
  function dist(ax: number, ay: number, bx: number, by: number) { return Math.hypot(ax - bx, ay - by); }

  function reset() {
    ship = mkShip();
    bullets = [];
    asteroids = Array.from({ length: 5 }, () => spawnAsteroid());
    score = 0;
    dead = false;
  }

  function shoot() {
    bullets.push({
      x: ship.x + Math.cos(ship.angle) * SHIP_SIZE,
      y: ship.y + Math.sin(ship.angle) * SHIP_SIZE,
      dx: Math.cos(ship.angle) * BULLET_SPEED + ship.dx * 0.3,
      dy: Math.sin(ship.angle) * BULLET_SPEED + ship.dy * 0.3,
      life: BULLET_LIFE,
    });
  }

  function tick() {
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    // ── update ──
    if (!dead) {
      if (keys.has("ArrowLeft")) ship.angle -= TURN_SPEED;
      if (keys.has("ArrowRight")) ship.angle += TURN_SPEED;
      if (keys.has("ArrowUp")) {
        ship.dx += Math.cos(ship.angle) * THRUST;
        ship.dy += Math.sin(ship.angle) * THRUST;
      }
      ship.dx *= FRICTION;
      ship.dy *= FRICTION;
      ship.x = wrap(ship.x + ship.dx, W);
      ship.y = wrap(ship.y + ship.dy, H);

      for (const b of bullets) { b.x = wrap(b.x + b.dx, W); b.y = wrap(b.y + b.dy, H); b.life--; }
      bullets = bullets.filter((b) => b.life > 0);

      for (const a of asteroids) { a.x = wrap(a.x + a.dx, W); a.y = wrap(a.y + a.dy, H); }

      // bullet-asteroid collisions
      const next: Asteroid[] = [];
      const spent = new Set<Bullet>();
      for (const a of asteroids) {
        let hit = false;
        for (const b of bullets) {
          if (spent.has(b)) continue;
          if (dist(a.x, a.y, b.x, b.y) < a.size) {
            hit = true;
            spent.add(b);
            score += (3 - SIZES.indexOf(a.size)) * 50;
            const si = SIZES.indexOf(a.size);
            if (si < SIZES.length - 1) {
              next.push(spawnAsteroid(a.x, a.y, si + 1));
              next.push(spawnAsteroid(a.x, a.y, si + 1));
            }
            break;
          }
        }
        if (!hit) next.push(a);
      }
      asteroids = next;
      bullets = bullets.filter((b) => !spent.has(b));

      if (asteroids.length === 0) {
        for (let i = 0; i < 5 + Math.floor(score / 500); i++) asteroids.push(spawnAsteroid());
      }

      for (const a of asteroids) {
        if (dist(ship.x, ship.y, a.x, a.y) < a.size + SHIP_SIZE * 0.5) { dead = true; break; }
      }
    }

    // ── draw ──
    ctx.fillStyle = "#0e0e0e";
    ctx.fillRect(0, 0, W, H);

    ctx.strokeStyle = "#555";
    ctx.lineWidth = 1;
    for (const a of asteroids) {
      ctx.beginPath();
      const n = a.verts.length;
      for (let i = 0; i <= n; i++) {
        const ang = (i / n) * Math.PI * 2;
        const r = a.verts[i % n];
        const px = a.x + Math.cos(ang) * r;
        const py = a.y + Math.sin(ang) * r;
        if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
      }
      ctx.stroke();
    }

    ctx.fillStyle = "#888";
    for (const b of bullets) ctx.fillRect(b.x - 1, b.y - 1, 2, 2);

    // ship
    ctx.strokeStyle = dead ? "#503030" : "#888";
    ctx.lineWidth = 1.5;
    const cos = Math.cos(ship.angle);
    const sin = Math.sin(ship.angle);
    const nose = { x: ship.x + cos * SHIP_SIZE, y: ship.y + sin * SHIP_SIZE };
    const left = { x: ship.x + Math.cos(ship.angle + 2.3) * SHIP_SIZE * 0.8, y: ship.y + Math.sin(ship.angle + 2.3) * SHIP_SIZE * 0.8 };
    const right = { x: ship.x + Math.cos(ship.angle - 2.3) * SHIP_SIZE * 0.8, y: ship.y + Math.sin(ship.angle - 2.3) * SHIP_SIZE * 0.8 };
    ctx.beginPath();
    ctx.moveTo(nose.x, nose.y);
    ctx.lineTo(left.x, left.y);
    ctx.lineTo(right.x, right.y);
    ctx.closePath();
    ctx.stroke();

    if (keys.has("ArrowUp") && !dead) {
      ctx.strokeStyle = "#666";
      ctx.lineWidth = 1;
      const tail = { x: ship.x - cos * SHIP_SIZE * (0.6 + Math.random() * 0.4), y: ship.y - sin * SHIP_SIZE * (0.6 + Math.random() * 0.4) };
      ctx.beginPath();
      ctx.moveTo(left.x, left.y);
      ctx.lineTo(tail.x, tail.y);
      ctx.lineTo(right.x, right.y);
      ctx.stroke();
    }

    ctx.fillStyle = "#555";
    ctx.font = "12px Monaco, monospace";
    ctx.fillText(`score: ${score}`, 8, 16);

    if (dead) {
      ctx.fillStyle = "#888";
      ctx.font = "14px Monaco, monospace";
      ctx.textAlign = "center";
      ctx.fillText("game over — press R to restart", W / 2, H / 2);
      ctx.textAlign = "start";
    }

    animFrame = requestAnimationFrame(tick);
  }

  function onKeyDown(e: KeyboardEvent) {
    if (["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", " "].includes(e.key)) e.preventDefault();
    keys.add(e.key);
    if (e.key === " " && !dead) shoot();
    if ((e.key === "r" || e.key === "R") && dead) reset();
  }

  function onKeyUp(e: KeyboardEvent) { keys.delete(e.key); }

  function start() {
    reset();
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    animFrame = requestAnimationFrame(tick);
  }

  function stop() {
    cancelAnimationFrame(animFrame);
    window.removeEventListener("keydown", onKeyDown);
    window.removeEventListener("keyup", onKeyUp);
    keys.clear();
  }

  $effect(() => {
    if (canvas) {
      start();
      return () => stop();
    }
  });
</script>

<canvas bind:this={canvas} width={W} height={H} class="game-canvas"></canvas>
<p class="hint">arrows: move · space: shoot · r: restart</p>

<style>
  .game-canvas {
    margin-top: 1rem;
    border: 1px solid #222;
    display: block;
  }
  .hint { margin-top: 0.3rem; font-size: 11px; color: #555; }
</style>
