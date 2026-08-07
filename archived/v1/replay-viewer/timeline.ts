// ARCHIVED: Sugarscape v1 is archival-only; do not extend or release this code.
let frameCount: i32 = 0;
let frameIndex: i32 = 0;
let playing: bool = false;
let speed: f64 = 1.0;
let frameDurationMs: f64 = 40.0;
let accumulatedMs: f64 = 0.0;

function clampFrame(index: i32): i32 {
  if (frameCount <= 0 || index <= 0) return 0;
  const last = frameCount - 1;
  return index >= last ? last : index;
}

export function configure(count: i32, durationMs: f64): i32 {
  frameCount = max(0, count);
  frameDurationMs = durationMs > 0.0 ? durationMs : 40.0;
  frameIndex = 0;
  accumulatedMs = 0.0;
  playing = false;
  speed = 1.0;
  return frameIndex;
}

export function seek(index: i32): i32 {
  frameIndex = clampFrame(index);
  accumulatedMs = 0.0;
  return frameIndex;
}

export function setPlaying(value: i32): i32 {
  playing = value != 0 && frameCount > 1 && frameIndex < frameCount - 1;
  accumulatedMs = 0.0;
  return playing ? 1 : 0;
}

export function isPlaying(): i32 {
  return playing ? 1 : 0;
}

export function setSpeed(value: f64): f64 {
  speed = value > 0.0 ? value : 1.0;
  return speed;
}

export function advance(elapsedMs: f64): i32 {
  if (!playing || frameCount <= 1 || elapsedMs <= 0.0) return frameIndex;
  accumulatedMs += elapsedMs * speed;
  const steps = i32(Math.floor(accumulatedMs / frameDurationMs));
  if (steps <= 0) return frameIndex;
  accumulatedMs -= f64(steps) * frameDurationMs;
  frameIndex = clampFrame(frameIndex + steps);
  if (frameIndex >= frameCount - 1) {
    playing = false;
    accumulatedMs = 0.0;
  }
  return frameIndex;
}
