#!/usr/bin/env node
// Vendor the broadcast typefaces into the repo as subset woff2 files.
//
// The replay is embedded in a sandboxed iframe behind the Observatory's k8s proxy,
// which cannot reach a CDN - a webfont linked to fonts.gstatic.com silently falls
// back and the broadcast loses its identity. So the faces are fetched once, here,
// and committed; the viewer build inlines them as data URIs.
//
//   node tools/vendor_fonts.mjs

import { mkdir, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const outputDir = join(root, "src/sugarscape/fonts");

// A browser UA is required or Google Fonts serves ttf instead of woff2.
const USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) " +
  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36";

// Every glyph the broadcast can render: the full printable ASCII range plus the
// handful of typographic marks the HUD uses. Subsetting keeps each face ~10 KB.
const TEXT = " !\"#$%&'()*+,-./0123456789:;<=>?@" +
  "ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`" +
  "abcdefghijklmnopqrstuvwxyz{|}~" +
  "×·–—‘’“”…→▲▼●";

const faces = [
  { family: "Space Grotesk", weights: [500, 700], file: "space-grotesk" },
  { family: "IBM Plex Mono", weights: [500, 600], file: "ibm-plex-mono" },
];

await mkdir(outputDir, { recursive: true });
const manifest = [];

for (const face of faces) {
  const query = new URLSearchParams({
    family: `${face.family}:wght@${face.weights.join(";")}`,
    text: TEXT,
    display: "swap",
  });
  const cssResponse = await fetch(`https://fonts.googleapis.com/css2?${query}`, {
    headers: { "User-Agent": USER_AGENT },
  });
  if (!cssResponse.ok) throw new Error(`css ${face.family}: ${cssResponse.status}`);
  const css = await cssResponse.text();

  const blocks = css.split("@font-face").slice(1);
  if (blocks.length !== face.weights.length) {
    throw new Error(`${face.family}: expected ${face.weights.length} faces, got ${blocks.length}`);
  }
  for (const block of blocks) {
    const weight = Number(/font-weight:\s*(\d+)/.exec(block)[1]);
    // A subset request returns a dynamic /l/font?kit=... URL, so the format comes
    // from the declaration rather than the file extension.
    const [, url, format] = /src:\s*url\(([^)]+)\)\s*format\('([^']+)'\)/.exec(block);
    if (format !== "woff2") throw new Error(`${face.family} ${weight}: got ${format}, not woff2`);
    const fontResponse = await fetch(url, { headers: { "User-Agent": USER_AGENT } });
    if (!fontResponse.ok) throw new Error(`font ${face.family} ${weight}: ${fontResponse.status}`);
    const bytes = Buffer.from(await fontResponse.arrayBuffer());
    const name = `${face.file}-${weight}.woff2`;
    await writeFile(join(outputDir, name), bytes);
    manifest.push({ name, family: face.family, weight, bytes: bytes.length });
    console.log(`${name.padEnd(28)} ${String(bytes.length).padStart(6)} bytes`);
  }
}

const total = manifest.reduce((sum, entry) => sum + entry.bytes, 0);
console.log(`\n${manifest.length} faces, ${(total / 1024).toFixed(1)} KB total`);
