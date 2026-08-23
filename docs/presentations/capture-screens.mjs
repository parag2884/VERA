/**
 * Capture VERA Studio screens for the manager deck.
 * Usage: node docs/presentations/capture-screens.mjs
 */
import { chromium } from "playwright";
import path from "node:path";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const outDir = path.join(__dirname, "screenshots");
const base = process.env.VERA_STUDIO_URL || "http://localhost:5173";

fs.mkdirSync(outDir, { recursive: true });

async function shot(page, name, fullPage = false) {
  const file = path.join(outDir, `${name}.png`);
  await page.waitForTimeout(600);
  await page.screenshot({ path: file, fullPage });
  console.log("saved", file);
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 1,
  });

  // Home / fleet
  await page.goto(`${base}/`, { waitUntil: "networkidle", timeout: 60000 });
  await shot(page, "01-home-fleet");

  // Prove-it if findings exist
  const prove = page.locator("button.finding-btn, .finding-prove").first();
  if (await prove.count()) {
    await prove.click().catch(() => {});
    await page.waitForTimeout(800);
    await shot(page, "02-prove-it-drawer");
    await page.keyboard.press("Escape").catch(() => {});
    const close = page.locator(".proof-drawer button", { hasText: "Close" });
    if (await close.count()) await close.click().catch(() => {});
    await page.waitForTimeout(400);
  }

  // Fleet
  await page.goto(`${base}/fleet`, { waitUntil: "networkidle", timeout: 60000 });
  await shot(page, "03-fleet");

  // Connect
  await page.goto(`${base}/connect`, { waitUntil: "networkidle", timeout: 60000 });
  await shot(page, "04-connect");

  // Ask
  await page.goto(`${base}/ask`, { waitUntil: "networkidle", timeout: 60000 });
  await shot(page, "05-ask");

  // Map — full page + high-DPI hero of the graph canvas
  await page.goto(`${base}/map`, { waitUntil: "networkidle", timeout: 60000 });
  await page.waitForTimeout(3500);
  await shot(page, "06-knowledge-map");

  const mapPage = await browser.newPage({
    viewport: { width: 1920, height: 1080 },
    deviceScaleFactor: 2,
  });
  await mapPage.goto(`${base}/map`, { waitUntil: "networkidle", timeout: 60000 });
  await mapPage.waitForTimeout(4000);
  const canvas = mapPage.locator(".map-canvas").first();
  if (await canvas.count()) {
    await canvas.screenshot({
      path: path.join(outDir, "06-knowledge-map-hero.png"),
    });
    console.log("saved", path.join(outDir, "06-knowledge-map-hero.png"));
  } else {
    await mapPage.screenshot({
      path: path.join(outDir, "06-knowledge-map-hero.png"),
    });
    console.log("saved (full page fallback)", path.join(outDir, "06-knowledge-map-hero.png"));
  }
  await mapPage.close();

  // Insights if present
  await page.goto(`${base}/insights`, { waitUntil: "networkidle", timeout: 60000 }).catch(() => null);
  if (page.url().includes("insights")) await shot(page, "07-insights");

  // Agent / deploy / embed surfaces
  await page.goto(`${base}/agent`, { waitUntil: "networkidle", timeout: 60000 }).catch(() => null);
  if (page.url().includes("agent")) await shot(page, "08-agent-builder");

  await page.goto(`${base}/deploy`, { waitUntil: "networkidle", timeout: 60000 }).catch(() => null);
  if (page.url().includes("deploy")) await shot(page, "09-deploy");

  await browser.close();
  console.log("done");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
