// Extract positioned text from a pdf.js document into the parser's page format.
// Works with pdfjs-dist in the browser and in Node.

export async function extractPages(pdf) {
  const pages = [];
  for (let n = 1; n <= pdf.numPages; n++) {
    const page = await pdf.getPage(n);
    const vp = page.getViewport({ scale: 1 });
    const content = await page.getTextContent();
    const items = [];
    for (const it of content.items) {
      if (!it.str || !it.str.trim()) continue;
      const [a, b, , d, e, f] = it.transform;
      const h = Math.hypot(b, d) || Math.abs(d) || it.height || 8;
      // Skip rotated text (watermarks, side margins).
      if (Math.abs(b) > 0.01 * Math.abs(a || 1)) continue;
      items.push({ str: it.str, x: e, y: vp.height - f - h * 0.8, w: it.width, h });
    }
    pages.push({ items });
    page.cleanup();
  }
  return pages;
}
