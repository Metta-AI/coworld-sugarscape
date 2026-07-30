#!/usr/bin/env node
// Generate the Sugarscape broadcast art batch with nanobanana (Gemini image models).
//
// Every prompt carries the SAME locked style sentence from the Phase-0c art-direction
// lock, so the whole batch coheres. The batch is TERRAIN ONLY: the settlers are drawn
// as flat discs in the viewer, because painterly agent sprites aliased badly at a ~9px
// cell and buried the thing an agent-based model has to show - where the population is
// and which policy owns it.
//
//   node tools/generate_art.mjs            # only missing assets
//   node tools/generate_art.mjs --force    # regenerate everything

import { createHash } from "node:crypto";
import { readFile, mkdir, writeFile, access } from "node:fs/promises";
import { homedir } from "node:os";
import { join, resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const outputDir = join(root, "src/sugarscape/art");
const force = process.argv.includes("--force");
// The image models 503 under load; fall through the tiers rather than failing the batch.
const MODELS = ["gemini-3-pro-image", "gemini-3.1-flash-image", "gemini-2.5-flash-image"];

const settings = JSON.parse(await readFile(join(homedir(), ".gemini/settings.json"), "utf8"));
const apiKey = settings.apiKey;
if (!apiKey) throw new Error("no apiKey in ~/.gemini/settings.json");

// The Phase-0c lock, verbatim, on every prompt in the batch.
const STYLE = "Painted in the style of a 1996 Santa Fe Institute artificial-life " +
  "research plate re-lit for broadcast: warm amber and honey palette, hand-painted " +
  "gouache texture with visible grain, a thick warm-dark brown ink outline (never pure " +
  "black), raking light from the upper left, deep umber shadows. Muted, scientific, " +
  "tactile - not glossy, not neon, not digital.";

const assets = [
  {
    name: "terrain-barren",
    prompt: `A seamless top-down texture of exhausted barren ground - VERY DARK cold ` +
      `charcoal-brown earth, nearly black, dry and cracked, drained of all colour and ` +
      `all warmth, deep shadow in every crack. It must read as DEPLETED and EMPTY, much ` +
      `darker than surrounding terrain. No amber, no gold, no yellow anywhere. No ` +
      `plants, no objects, no creatures, no text. The texture fills the entire square ` +
      `frame edge to edge with no border and no background showing. ${STYLE}`,
  },
  ...[1, 2, 3, 4].map((tier) => ({
    name: `terrain-sugar-${tier}`,
    prompt: `A seamless top-down texture of ${[
      "a thin scattering of coarse amber sugar crystals over dark earth, mostly bare ground showing",
      "a broken crust of golden sugar granules covering about half the ground",
      "a thick continuous drift of glittering honey-gold sugar granules, ground barely visible",
      "a deep dense bank of brilliant pale-honey sugar crystals, luminous and heaped, completely covering the ground",
    ][tier - 1]}. Granular crystalline texture, no plants, no objects, no creatures, ` +
      `no text. The texture fills the entire square frame edge to edge with no border ` +
      `and no background showing. ${STYLE}`,
  })),
  {
    name: "endcard",
    prompt: `A wide cinematic vista looking down from high altitude onto a vast amber ` +
      `sugar massif rising out of dark barren plains, dust haze catching low warm light, ` +
      `deep umber shadows in the valleys. Empty landscape - no figures, no buildings, no ` +
      `text, no watermark. Dark and atmospheric enough that white text would sit ` +
      `comfortably on top of it. ${STYLE}`,
    aspect: "16:9",
  },
];

async function exists(path) {
  try { await access(path); return true; } catch { return false; }
}

async function generate(asset) {
  const body = {
    contents: [{ parts: [{ text: asset.prompt }] }],
    generationConfig: {
      responseModalities: ["IMAGE"],
      imageConfig: { aspectRatio: asset.aspect ?? "1:1" },
    },
  };
  let lastError = "";
  for (const model of MODELS) {
    for (let attempt = 0; attempt < 4; attempt += 1) {
      const response = await fetch(
        `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent`,
        {
          method: "POST",
          headers: { "content-type": "application/json", "x-goog-api-key": apiKey },
          body: JSON.stringify(body),
        },
      );
      if (response.ok) {
        const payload = await response.json();
        const part = payload.candidates?.[0]?.content?.parts?.find((entry) => entry.inlineData);
        if (part) return { bytes: Buffer.from(part.inlineData.data, "base64"), model };
        lastError = `${model}: no image in response`;
        break;
      }
      lastError = `${model}: ${response.status} ${(await response.text()).slice(0, 160)}`;
      if (response.status !== 503 && response.status !== 429) break;
      await new Promise((wait) => setTimeout(wait, 4000 * 2 ** attempt));
    }
  }
  throw new Error(`${asset.name}: ${lastError}`);
}

await mkdir(outputDir, { recursive: true });
for (const asset of assets) {
  const path = join(outputDir, `${asset.name}.png`);
  if (!force && await exists(path)) {
    console.log(`${asset.name.padEnd(20)} skip (exists)`);
    continue;
  }
  const { bytes, model } = await generate(asset);
  await writeFile(path, bytes);
  const digest = createHash("sha256").update(bytes).digest("hex").slice(0, 12);
  console.log(`${asset.name.padEnd(20)} ${String(bytes.length).padStart(8)} bytes  ${digest}  ${model}`);
}
console.log(`\n${assets.length} assets in ${outputDir}`);
