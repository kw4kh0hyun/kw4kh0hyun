import { getDocument } from 'pdfjs-dist/legacy/build/pdf.mjs';
import { extractPages } from '../lib/pdf-text.js';
export async function pagesFromBuffer(buf) {
  const pdf = await getDocument({ data: new Uint8Array(buf), verbosity: 0, isEvalSupported: false }).promise;
  return extractPages(pdf);
}
