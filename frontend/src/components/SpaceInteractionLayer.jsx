import { useEffect, useRef } from 'react';

// ── Web Audio Engine ─────────────────────────────────────────────────────────
let audioCtx = null;

function getAudioContext() {
  if (!audioCtx) {
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  }
  // Resume if suspended (browser policy)
  if (audioCtx.state === 'suspended') audioCtx.resume();
  return audioCtx;
}

/**
 * Synthesize a layered sci-fi space click sound:
 * - High-pitched laser chirp (sawtooth, descending freq)
 * - Sub-bass thump (sine, low freq punch)
 * - Short static crackle (white noise burst)
 */
function playSpaceClickSound() {
  try {
    const ctx = getAudioContext();
    const now = ctx.currentTime;

    // 1. Laser chirp — sawtooth sweep down
    const chirpOsc = ctx.createOscillator();
    const chirpGain = ctx.createGain();
    const chirpFilter = ctx.createBiquadFilter();
    chirpOsc.type = 'sawtooth';
    chirpOsc.frequency.setValueAtTime(1200, now);
    chirpOsc.frequency.exponentialRampToValueAtTime(180, now + 0.12);
    chirpFilter.type = 'bandpass';
    chirpFilter.frequency.value = 900;
    chirpFilter.Q.value = 2.5;
    chirpGain.gain.setValueAtTime(0, now);
    chirpGain.gain.linearRampToValueAtTime(0.22, now + 0.008);
    chirpGain.gain.exponentialRampToValueAtTime(0.001, now + 0.14);
    chirpOsc.connect(chirpFilter);
    chirpFilter.connect(chirpGain);
    chirpGain.connect(ctx.destination);
    chirpOsc.start(now);
    chirpOsc.stop(now + 0.15);

    // 2. Sub-bass thump — sine punch
    const bassOsc = ctx.createOscillator();
    const bassGain = ctx.createGain();
    bassOsc.type = 'sine';
    bassOsc.frequency.setValueAtTime(140, now);
    bassOsc.frequency.exponentialRampToValueAtTime(40, now + 0.09);
    bassGain.gain.setValueAtTime(0, now);
    bassGain.gain.linearRampToValueAtTime(0.35, now + 0.01);
    bassGain.gain.exponentialRampToValueAtTime(0.001, now + 0.10);
    bassOsc.connect(bassGain);
    bassGain.connect(ctx.destination);
    bassOsc.start(now);
    bassOsc.stop(now + 0.11);

    // 3. White noise crackle — short digital static burst
    const bufferSize = ctx.sampleRate * 0.04;
    const noiseBuffer = ctx.createBuffer(1, bufferSize, ctx.sampleRate);
    const noiseData = noiseBuffer.getChannelData(0);
    for (let i = 0; i < bufferSize; i++) noiseData[i] = Math.random() * 2 - 1;
    const noiseSource = ctx.createBufferSource();
    noiseSource.buffer = noiseBuffer;
    const noiseGain = ctx.createGain();
    const noiseFilter = ctx.createBiquadFilter();
    noiseFilter.type = 'highpass';
    noiseFilter.frequency.value = 3000;
    noiseGain.gain.setValueAtTime(0.08, now);
    noiseGain.gain.exponentialRampToValueAtTime(0.001, now + 0.04);
    noiseSource.connect(noiseFilter);
    noiseFilter.connect(noiseGain);
    noiseGain.connect(ctx.destination);
    noiseSource.start(now);
    noiseSource.stop(now + 0.04);
  } catch {
    // Silently fail if audio is blocked
  }
}

// ── Canvas Click Effect ───────────────────────────────────────────────────────
const COLORS = ['#00f3ff', '#00ff9d', '#00c8ff', '#7fffff', '#33ffe6'];

class ShockwaveRing {
  constructor(x, y, color) {
    this.x = x; this.y = y; this.color = color;
    this.r = 4; this.maxR = 80; this.alpha = 1; this.lw = 2.5;
  }
  update() {
    this.r += 4.5;
    this.alpha = Math.max(0, 1 - this.r / this.maxR);
    this.lw = Math.max(0.3, 2.5 * (1 - this.r / this.maxR));
    return this.alpha > 0 && this.r < this.maxR;
  }
  draw(ctx) {
    ctx.save();
    ctx.globalAlpha = this.alpha;
    ctx.shadowBlur = 18;
    ctx.shadowColor = this.color;
    ctx.strokeStyle = this.color;
    ctx.lineWidth = this.lw;
    ctx.beginPath();
    ctx.arc(this.x, this.y, this.r, 0, Math.PI * 2);
    ctx.stroke();
    ctx.restore();
  }
}

class SecondaryRing extends ShockwaveRing {
  constructor(x, y, color) {
    super(x, y, color);
    this.maxR = 50;
    this.delay = 3; // start a few frames later
  }
  update() {
    if (this.delay-- > 0) return true;
    return super.update();
  }
  draw(ctx) {
    if (this.delay > 0) return;
    super.draw(ctx);
  }
}

class Particle {
  constructor(x, y, color) {
    this.x = x; this.y = y;
    const angle = Math.random() * Math.PI * 2;
    const speed = 1.5 + Math.random() * 4.5;
    this.vx = Math.cos(angle) * speed;
    this.vy = Math.sin(angle) * speed;
    this.size = 1.2 + Math.random() * 3.2;
    this.color = color;
    this.alpha = 1;
    this.decay = 0.032 + Math.random() * 0.025;
    this.trail = []; // trail effect
  }
  update() {
    this.trail.push({ x: this.x, y: this.y, a: this.alpha });
    if (this.trail.length > 6) this.trail.shift();
    this.x += this.vx;
    this.y += this.vy;
    this.vy += 0.06; // slight gravity
    this.vx *= 0.97;
    this.alpha -= this.decay;
    return this.alpha > 0;
  }
  draw(ctx) {
    // Draw trail
    this.trail.forEach((pt, i) => {
      const ta = pt.a * (i / this.trail.length) * 0.4;
      ctx.save();
      ctx.globalAlpha = ta;
      ctx.fillStyle = this.color;
      ctx.shadowBlur = 6;
      ctx.shadowColor = this.color;
      ctx.beginPath();
      ctx.arc(pt.x, pt.y, this.size * 0.6, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    });
    ctx.save();
    ctx.globalAlpha = this.alpha;
    ctx.shadowBlur = 14;
    ctx.shadowColor = this.color;
    ctx.fillStyle = this.color;
    ctx.beginPath();
    ctx.arc(this.x, this.y, this.size, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }
}

class HexShard {
  // Diamond-shaped shard for more sci-fi feel
  constructor(x, y, color) {
    this.x = x; this.y = y;
    const angle = Math.random() * Math.PI * 2;
    const speed = 2.5 + Math.random() * 5;
    this.vx = Math.cos(angle) * speed;
    this.vy = Math.sin(angle) * speed;
    this.size = 3 + Math.random() * 6;
    this.rotation = Math.random() * Math.PI * 2;
    this.rotSpeed = (Math.random() - 0.5) * 0.25;
    this.color = color;
    this.alpha = 1;
    this.decay = 0.028 + Math.random() * 0.02;
  }
  update() {
    this.x += this.vx;
    this.y += this.vy;
    this.vy += 0.08;
    this.vx *= 0.96;
    this.rotation += this.rotSpeed;
    this.alpha -= this.decay;
    return this.alpha > 0;
  }
  draw(ctx) {
    ctx.save();
    ctx.globalAlpha = this.alpha;
    ctx.shadowBlur = 10;
    ctx.shadowColor = this.color;
    ctx.strokeStyle = this.color;
    ctx.lineWidth = 1.2;
    ctx.translate(this.x, this.y);
    ctx.rotate(this.rotation);
    // Diamond shape (4 points)
    ctx.beginPath();
    ctx.moveTo(0, -this.size);
    ctx.lineTo(this.size * 0.5, 0);
    ctx.lineTo(0, this.size);
    ctx.lineTo(-this.size * 0.5, 0);
    ctx.closePath();
    ctx.stroke();
    ctx.restore();
  }
}

class CrosshairFlash {
  // Momentary + sign at click origin
  constructor(x, y, color) {
    this.x = x; this.y = y; this.color = color;
    this.size = 24; this.alpha = 1; this.life = 12;
  }
  update() {
    this.life--;
    this.size += 1.8;
    this.alpha = this.life / 12;
    return this.life > 0;
  }
  draw(ctx) {
    ctx.save();
    ctx.globalAlpha = this.alpha;
    ctx.strokeStyle = this.color;
    ctx.lineWidth = 1.5;
    ctx.shadowBlur = 20;
    ctx.shadowColor = this.color;
    const s = this.size;
    const g = s * 0.28; // gap in center
    ctx.beginPath();
    ctx.moveTo(this.x - s, this.y); ctx.lineTo(this.x - g, this.y);
    ctx.moveTo(this.x + g, this.y); ctx.lineTo(this.x + s, this.y);
    ctx.moveTo(this.x, this.y - s); ctx.lineTo(this.x, this.y - g);
    ctx.moveTo(this.x, this.y + g); ctx.lineTo(this.x, this.y + s);
    ctx.stroke();
    ctx.restore();
  }
}

// ── Main Component ────────────────────────────────────────────────────────────
export default function SpaceInteractionLayer() {
  const canvasRef = useRef(null);
  const cursorRef = useRef(null);
  const particlesRef = useRef([]);
  const animRef = useRef(null);
  const mouseRef = useRef({ x: -200, y: -200 });
  const isClickingRef = useRef(false);
  const rotAngleRef = useRef(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    const resize = () => {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
    };
    resize();
    window.addEventListener('resize', resize);

    // Define loop entirely inside effect — avoids ref write during render
    let animId;
    const loop = () => {
      const ctx = canvas.getContext('2d');
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      particlesRef.current = particlesRef.current.filter(p => {
        const alive = p.update();
        if (alive) p.draw(ctx);
        return alive;
      });

      animId = requestAnimationFrame(loop);
    };

    animId = requestAnimationFrame(loop);
    animRef.current = { cancel: () => cancelAnimationFrame(animId) };

    return () => {
      window.removeEventListener('resize', resize);
      cancelAnimationFrame(animId);
    };
  }, []);

  // Mouse move — update cursor position
  useEffect(() => {
    const onMove = (e) => {
      mouseRef.current = { x: e.clientX, y: e.clientY };
      const el = cursorRef.current;
      if (el) {
        el.style.transform = `translate(${e.clientX}px, ${e.clientY}px)`;
      }
    };

    // Animate cursor rings
    let rafId;
    const animateCursor = () => {
      rotAngleRef.current += 0.8;
      const el = cursorRef.current;
      if (el) {
        const outerRing = el.querySelector('.cs-outer');
        const innerRing = el.querySelector('.cs-inner');
        if (outerRing) outerRing.style.transform = `rotate(${rotAngleRef.current}deg)`;
        if (innerRing) innerRing.style.transform = `rotate(${-rotAngleRef.current * 1.6}deg)`;
      }
      rafId = requestAnimationFrame(animateCursor);
    };

    const onClick = (e) => {
      const x = e.clientX;
      const y = e.clientY;
      const color = COLORS[Math.floor(Math.random() * COLORS.length)];
      const color2 = COLORS[Math.floor(Math.random() * COLORS.length)];

      // Sound
      playSpaceClickSound();

      // Effects
      particlesRef.current.push(
        new ShockwaveRing(x, y, color),
        new SecondaryRing(x, y, color2),
        new CrosshairFlash(x, y, '#ffffff'),
      );
      for (let i = 0; i < 14; i++) {
        particlesRef.current.push(new Particle(x, y, COLORS[Math.floor(Math.random() * COLORS.length)]));
      }
      for (let i = 0; i < 6; i++) {
        particlesRef.current.push(new HexShard(x, y, color));
      }
    };

    const onDown = () => {
      isClickingRef.current = true;
      const el = cursorRef.current;
      if (el) el.classList.add('cs-pressing');
    };
    const onUp = () => {
      isClickingRef.current = false;
      const el = cursorRef.current;
      if (el) el.classList.remove('cs-pressing');
    };

    window.addEventListener('mousemove', onMove);
    window.addEventListener('click', onClick);
    window.addEventListener('mousedown', onDown);
    window.addEventListener('mouseup', onUp);
    rafId = requestAnimationFrame(animateCursor);

    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('click', onClick);
      window.removeEventListener('mousedown', onDown);
      window.removeEventListener('mouseup', onUp);
      cancelAnimationFrame(rafId);
    };
  }, []);

  return (
    <>
      {/* Full-screen transparent canvas for click effects */}
      <canvas
        ref={canvasRef}
        style={{
          position: 'fixed', inset: 0, zIndex: 2147483646,
          pointerEvents: 'none', width: '100%', height: '100%',
        }}
      />

      {/* Custom cursor element */}
      <div
        ref={cursorRef}
        className="cs-root"
        style={{
          position: 'fixed', top: 0, left: 0,
          width: 0, height: 0,
          zIndex: 2147483647, pointerEvents: 'none',
          willChange: 'transform',
        }}
      >
        {/* Outer rotating dashed ring */}
        <svg
          className="cs-outer"
          viewBox="0 0 60 60"
          style={{
            position: 'absolute',
            width: 52, height: 52,
            top: -26, left: -26,
            transformOrigin: 'center',
          }}
        >
          <circle cx="30" cy="30" r="26"
            stroke="#00f3ff" strokeWidth="1.2" fill="none"
            strokeDasharray="6 5"
            style={{ filter: 'drop-shadow(0 0 4px #00f3ff)' }}
          />
          {/* Corner tick marks */}
          {[0, 90, 180, 270].map(angle => {
            const rad = (angle * Math.PI) / 180;
            return (
              <line key={angle}
                x1={30 + 22 * Math.cos(rad)} y1={30 + 22 * Math.sin(rad)}
                x2={30 + 29 * Math.cos(rad)} y2={30 + 29 * Math.sin(rad)}
                stroke="#00f3ff" strokeWidth="1.8"
                style={{ filter: 'drop-shadow(0 0 3px #00f3ff)' }}
              />
            );
          })}
        </svg>

        {/* Inner counter-rotating ring */}
        <svg
          className="cs-inner"
          viewBox="0 0 40 40"
          style={{
            position: 'absolute',
            width: 28, height: 28,
            top: -14, left: -14,
            transformOrigin: 'center',
          }}
        >
          <circle cx="20" cy="20" r="11"
            stroke="#00ff9d" strokeWidth="1" fill="none"
            strokeDasharray="3 4"
            style={{ filter: 'drop-shadow(0 0 3px #00ff9d)' }}
          />
        </svg>

        {/* Static crosshair lines */}
        <svg
          viewBox="0 0 60 60"
          style={{
            position: 'absolute',
            width: 52, height: 52,
            top: -26, left: -26,
            pointerEvents: 'none',
          }}
        >
          {/* Horizontal */}
          <line x1="0" y1="30" x2="22" y2="30" stroke="#00f3ff" strokeWidth="1" opacity="0.8" />
          <line x1="38" y1="30" x2="60" y2="30" stroke="#00f3ff" strokeWidth="1" opacity="0.8" />
          {/* Vertical */}
          <line x1="30" y1="0" x2="30" y2="22" stroke="#00f3ff" strokeWidth="1" opacity="0.8" />
          <line x1="30" y1="38" x2="30" y2="60" stroke="#00f3ff" strokeWidth="1" opacity="0.8" />
          {/* Center dot */}
          <circle cx="30" cy="30" r="2" fill="#00f3ff"
            style={{ filter: 'drop-shadow(0 0 6px #00f3ff)' }}
          />
        </svg>
      </div>

      <style>{`
        html, body, * { cursor: none !important; }

        .cs-root svg { transition: none; }

        /* Press scale effect */
        .cs-pressing .cs-outer {
          animation: cs-pulse 0.15s ease-out forwards !important;
        }
        @keyframes cs-pulse {
          0%   { transform: rotate(var(--r, 0deg)) scale(1); }
          50%  { transform: rotate(var(--r, 0deg)) scale(0.72); }
          100% { transform: rotate(var(--r, 0deg)) scale(1); }
        }
      `}</style>
    </>
  );
}