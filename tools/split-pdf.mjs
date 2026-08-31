/**
 * split-pdf.mjs — split a large PDF into page-range markdown parts for llmwiki ingest.
 *
 * Why this exists: `llmwiki ingest` hard-truncates every source at 100,000 chars
 * (MAX_SOURCE_CHARS). A ~150-page model documentation PDF extracts to 400k-700k
 * chars, so ingesting the whole PDF would silently keep only the first ~25-35
 * pages. Splitting first keeps every page in the knowledge base and gives the
 * compiler chapter-sized sources, which improves concept extraction granularity.
 *
 * Each part is written as:
 *   <out-dir>/<pdf-slug>_part-NN_pages-XXXX-YYYY.md
 * with `[page N]` markers between pages so compiled-page citations (which point
 * into these files by line range) can be mapped back to original PDF pages.
 *
 * Usage:
 *   node tools/split-pdf.mjs <input.pdf> [--out-dir sources] [--max-chars 60000]
 *
 * Example:
 *   node tools/split-pdf.mjs ~/docs/model-a.pdf
 *   node tools/split-pdf.mjs ~/docs/model-a.pdf --max-chars 40000 --out-dir sources
 */

import { readFile, mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { PDFParse } from "pdf-parse";

/** Default per-part character budget. 60k chars ≈ 15-20k tokens: well under the
 * 100k ingest cap and comfortable for 32k-context extraction models. */
const DEFAULT_MAX_CHARS = 60_000;

/** Parse CLI args: positional pdf path plus --out-dir and --max-chars flags. */
function parseArgs(argv) {
  const args = { pdfPath: null, outDir: "sources", maxChars: DEFAULT_MAX_CHARS };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--out-dir") args.outDir = argv[++i];
    else if (arg === "--max-chars") args.maxChars = Number(argv[++i]);
    else if (!arg.startsWith("--")) args.pdfPath = arg;
  }
  if (!args.pdfPath) {
    console.error("usage: node tools/split-pdf.mjs <input.pdf> [--out-dir sources] [--max-chars 60000]");
    process.exit(2);
  }
  if (!Number.isFinite(args.maxChars) || args.maxChars <= 0) {
    console.error(`--max-chars must be a positive number, got: ${args.maxChars}`);
    process.exit(2);
  }
  return args;
}

/** Turn a PDF filename into a filesystem-safe slug for part names. */
function slugify(filePath) {
  return path
    .basename(filePath, path.extname(filePath))
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

/**
 * Group per-page text into parts under the char budget. A single page larger
 * than the budget becomes its own part (llmwiki truncates at 100k, so a page
 * beyond that would lose text — warn when that happens).
 */
function groupPages(pages, maxChars) {
  const parts = [];
  let current = [];
  let currentChars = 0;
  for (const page of pages) {
    const pageBlock = `\n[page ${page.num}]\n\n${page.text.trim()}\n`;
    if (current.length > 0 && currentChars + pageBlock.length > maxChars) {
      parts.push(current);
      current = [];
      currentChars = 0;
    }
    current.push({ num: page.num, block: pageBlock });
    currentChars += pageBlock.length;
    if (pageBlock.length > maxChars) {
      console.warn(`warning: page ${page.num} alone is ${pageBlock.length} chars (> budget ${maxChars})`);
    }
  }
  if (current.length > 0) parts.push(current);
  return parts;
}

/** Render one part file: title heading, provenance comment, page-marked body. */
function renderPart({ title, pdfName, partIndex, partCount, pages }) {
  const first = pages[0].num;
  const last = pages[pages.length - 1].num;
  const header = [
    `# ${title} — part ${partIndex + 1} of ${partCount} (pages ${first}–${last})`,
    "",
    `<!-- source-pdf: ${pdfName} | part ${partIndex + 1}/${partCount} | pages ${first}-${last} -->`,
    "",
  ].join("\n");
  return header + pages.map((p) => p.block).join("\n");
}

async function main() {
  const { pdfPath, outDir, maxChars } = parseArgs(process.argv.slice(2));
  const slug = slugify(pdfPath);
  const pdfName = path.basename(pdfPath);

  const buffer = await readFile(pdfPath);
  const parser = new PDFParse({ data: new Uint8Array(buffer) });
  let pages;
  let title = slug;
  try {
    // Sequential calls are required: pdfjs-dist's LoopbackPort uses
    // structuredClone internally and concurrent calls throw DataCloneError.
    const textResult = await parser.getText({ pageJoiner: "" });
    const info = await parser.getInfo().catch(() => null);
    if (info?.info?.Title && typeof info.info.Title === "string") {
      title = info.info.Title.trim() || slug;
    }
    pages = textResult.pages;
  } finally {
    await parser.destroy();
  }

  const emptyPages = pages.filter((p) => p.text.trim().length === 0);
  if (emptyPages.length > 0) {
    console.warn(
      `warning: ${emptyPages.length}/${pages.length} pages extracted no text ` +
      `(e.g. page ${emptyPages[0].num}). Scanned pages need OCR before ingest.`,
    );
  }

  const parts = groupPages(pages, maxChars);
  await mkdir(outDir, { recursive: true });

  const pad = String(parts.length).length;
  for (let i = 0; i < parts.length; i += 1) {
    const partPages = parts[i];
    const first = String(partPages[0].num).padStart(4, "0");
    const last = String(partPages[partPages.length - 1].num).padStart(4, "0");
    const fileName = `${slug}_part-${String(i + 1).padStart(pad, "0")}_pages-${first}-${last}.md`;
    const body = renderPart({ title, pdfName, partIndex: i, partCount: parts.length, pages: partPages });
    await writeFile(path.join(outDir, fileName), body, "utf-8");
    console.log(`wrote ${fileName} (${body.length} chars, pages ${first}-${last})`);
  }
  console.log(`done: ${parts.length} parts from ${pages.length} pages → ${outDir}/`);
}

main().catch((err) => {
  console.error(`split-pdf failed: ${err.message}`);
  process.exit(1);
});
