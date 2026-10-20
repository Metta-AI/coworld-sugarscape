/** Research snapshots retain their own semantics; the DTL replay reader is unchanged. */
function showResearchReplay(replay) {
  if (!Array.isArray(replay.frames) || replay.frames.length === 0 || !replay.details) {
    throw new Error("Research replay has no complete frames or provenance");
  }
  stopPaintLoop();
  state.playing = false;
  const panel = document.createElement("section");
  panel.id = "research-replay";
  panel.style.cssText = "position:fixed;inset:0;z-index:100;background:#14100a;color:#f6ead2;padding:20px;overflow:auto;font:16px system-ui;box-sizing:border-box";
  const title = document.createElement("h1");
  title.textContent = replay.details.study.replaceAll("_", " ");
  const qualification = document.createElement("p");
  qualification.textContent = replay.details.mode === "reference"
    ? "Reference experiment · noncompetitive score · native rules preserved"
    : "Population calibration challenge · score and parameter controls are a Coworld adaptation";
  if (replay.details.duration_override) qualification.textContent += " · duration differs from the study protocol";
  if (replay.details.provenance.recorder_scope) qualification.textContent += " · " + replay.details.provenance.recorder_scope;
  const row = document.createElement("div");
  row.style.cssText = "display:flex;gap:24px;flex-wrap:wrap;align-items:flex-start";
  const board = document.createElement("canvas");
  board.width = 700; board.height = 700;
  board.style.cssText = "width:min(68vh,90vw);height:auto;background:#211a10";
  board.setAttribute("aria-label", "Native resources and scheduled agents at the selected timestep");
  const readings = document.createElement("pre");
  readings.style.cssText = "white-space:pre-wrap;max-width:42em;font:15px ui-monospace,monospace";
  row.append(board, readings);
  const controls = document.createElement("div");
  controls.style.cssText = "display:flex;gap:12px;align-items:center;margin:12px 0";
  const toggle = document.createElement("button");
  toggle.textContent = "Pause";
  const slider = document.createElement("input");
  slider.type = "range"; slider.min = "0"; slider.max = String(replay.frames.length - 1); slider.value = "0";
  slider.style.width = "min(70vw,700px)";
  slider.setAttribute("aria-label", "Research timestep");
  const tickLabel = document.createElement("span");
  controls.append(toggle, slider, tickLabel);
  const provenance = document.createElement("details");
  const summary = document.createElement("summary");
  summary.textContent = "Study parameters and source provenance";
  const source = document.createElement("pre");
  source.style.cssText = "white-space:pre-wrap;overflow-wrap:anywhere";
  source.textContent = JSON.stringify(replay.details, null, 2);
  provenance.append(summary, source);
  panel.append(title, qualification, controls, row, provenance);
  for (const previous of document.body.children) if (previous.tagName !== "SCRIPT") previous.hidden = true;
  document.body.append(panel);
  let index = 0;
  let playing = true;
  const context = board.getContext("2d");
  const render = () => {
    const frame = replay.frames[index];
    board.hidden = frame.width === 0;
    const cellWidth = frame.width === 0 ? 0 : board.width / frame.width;
    const cellHeight = frame.height === 0 ? 0 : board.height / frame.height;
    context.clearRect(0, 0, board.width, board.height);
    for (let x = 0; x < frame.width; x += 1) {
      for (let y = 0; y < frame.height; y += 1) {
        const position = x * frame.height + y;
        const sugar = Math.min(1, frame.sugar[position] / 4);
        const spice = Math.min(1, frame.spice[position] / 4);
        context.fillStyle = `rgb(${35 + sugar * 170},${28 + sugar * 112 + spice * 35},${17 + spice * 100})`;
        context.fillRect(x * cellWidth, y * cellHeight, cellWidth, cellHeight);
      }
    }
    context.fillStyle = "#6b8bff";
    for (const agent of frame.agents) {
      context.beginPath();
      context.arc((agent[1] + 0.5) * cellWidth, (agent[2] + 0.5) * cellHeight, Math.max(2, cellWidth * 0.28), 0, Math.PI * 2);
      context.fill();
    }
    readings.textContent = Object.entries(frame.measurements).map(([name, value]) => `${name}: ${typeof value === "number" && !Number.isInteger(value) ? value.toFixed(6) : value}`).join("\n");
    readings.textContent += "\n\nNative state SHA-256:\n" + frame.native_state_sha256;
    if (replay.details.study === "mcculloch_2022") readings.textContent += "\n\nBlue dots are scheduled agents. Physical occupancy also includes inactive collision occupants, as in the released model.";
    if (replay.details.study === "dogan_2026") readings.textContent += "\n\nOwners are off-grid accounting identities. Population, wealth and Gini include owners; the board shows on-grid agents.";
    if (replay.details.study === "izquierdo_2009") readings.textContent += "\n\nControlled positive-probability witness. This path does not estimate stationary probabilities or mixing time.";
    slider.value = String(index);
    tickLabel.textContent = `Tick ${frame.timestep} / ${replay.frames.at(-1).timestep}`;
    panel.dataset.timestep = String(frame.timestep);
  };
  toggle.onclick = () => { playing = !playing; toggle.textContent = playing ? "Pause" : "Play"; };
  slider.oninput = () => { index = Number(slider.value); render(); };
  render();
  requestAnimationFrame(() => tellHost({ type: "ready" }));
  const timer = setInterval(() => {
    if (!panel.isConnected) { clearInterval(timer); return; }
    if (playing) { index = (index + 1) % replay.frames.length; render(); }
  }, 120);
}
