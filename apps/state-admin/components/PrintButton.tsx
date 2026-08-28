"use client";

/**
 * The report export (Section 9.3).
 *
 * The browser's own print dialogue over the print stylesheet in globals.css.
 * No PDF library, no server-side renderer, no second definition of the layout
 * that can drift from this one — and the output is a real PDF an official can
 * file or forward.
 */
export function PrintButton() {
  return (
    <button type="button" className="btn no-print" onClick={() => window.print()}>
      Export report as PDF
    </button>
  );
}
