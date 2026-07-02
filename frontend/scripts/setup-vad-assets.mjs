/**
 * Vendor the VAD runtime assets into public/ so the Silero VAD worker can load them
 * at runtime from a same-origin URL (a bare 'onnxruntime-web' specifier can't resolve
 * inside a browser worker, so the files must be self-hosted).
 *
 *   public/onnx/ort.wasm.bundle.min.mjs      (+ ort-wasm-simd-threaded.{mjs,wasm})
 *   public/models/silero_vad.onnx            (Silero VAD v4 — input/sr/h/c interface)
 *
 * Run: npm run setup:vad  (also wired into postinstall). Non-fatal: if node_modules
 * isn't populated yet or the network is down it warns and exits 0 so installs/CI don't
 * break — the app still runs on the energy-VAD fallback, just less reliably.
 */
import { createWriteStream, existsSync, mkdirSync, copyFileSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { get } from 'node:https';

const here = dirname(fileURLToPath(import.meta.url));
const frontend = join(here, '..');
const onnxDir = join(frontend, 'public', 'onnx');
const modelsDir = join(frontend, 'public', 'models');

// onnxruntime-web dist files needed for the wasm EP, single-threaded.
const ORT_FILES = [
  'ort.wasm.bundle.min.mjs',
  'ort-wasm-simd-threaded.mjs',
  'ort-wasm-simd-threaded.wasm',
];
const ortDist = join(frontend, 'node_modules', 'onnxruntime-web', 'dist');

// Silero VAD v4 — must be the v4 ONNX (input/sr/h/c -> output/hn/cn); v5 has a
// different interface and would silently fail the worker's tensor wiring.
const SILERO_URL =
  'https://github.com/snakers4/silero-vad/raw/v4.0/files/silero_vad.onnx';
const sileroPath = join(modelsDir, 'silero_vad.onnx');

function ensureDir(d) {
  if (!existsSync(d)) mkdirSync(d, { recursive: true });
}

function copyOrtFiles() {
  if (!existsSync(ortDist)) {
    console.warn(
      `[setup:vad] onnxruntime-web not found at ${ortDist} — run "npm install" first. Skipping.`
    );
    return;
  }
  ensureDir(onnxDir);
  for (const f of ORT_FILES) {
    const src = join(ortDist, f);
    if (!existsSync(src)) {
      console.warn(`[setup:vad] missing ${f} in onnxruntime-web dist — skipping.`);
      continue;
    }
    copyFileSync(src, join(onnxDir, f));
    console.log(`[setup:vad] copied ${f}`);
  }
}

function downloadSilero() {
  if (existsSync(sileroPath) && statSync(sileroPath).size > 0) {
    console.log('[setup:vad] silero_vad.onnx already present — skipping download.');
    return;
  }
  ensureDir(modelsDir);
  const download = (url) =>
    get(url, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        download(res.headers.location); // follow redirect (GitHub -> raw CDN)
        return;
      }
      if (res.statusCode !== 200) {
        console.warn(`[setup:vad] silero download failed (HTTP ${res.statusCode}). Skipping.`);
        res.resume();
        return;
      }
      const out = createWriteStream(sileroPath);
      res.pipe(out);
      out.on('finish', () => out.close(() => console.log('[setup:vad] downloaded silero_vad.onnx')));
    }).on('error', (e) => console.warn(`[setup:vad] silero download error: ${e.message}. Skipping.`));
  download(SILERO_URL);
}

copyOrtFiles();
downloadSilero();
