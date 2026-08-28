import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

/**
 * The two apps share a palette by hand.
 *
 * A shared workspace package was considered and declined for two consumers, so
 * this test is what stops "kept in sync by hand" from being a hope. It compares
 * everything from `:root {` onwards, which is the whole token set; the header
 * comment above that line is allowed to differ because it explains a different
 * app.
 *
 * If this fails, the two surfaces have drifted apart and an officer moving
 * between them will see it.
 */

function tokenBody(path: string): string {
  const text = readFileSync(resolve(__dirname, "..", path), "utf8");
  // Anchored to the start of a line, so a header comment that happens to
  // mention the selector does not get matched instead of the rule. (It did.)
  const match = /^:root \{/m.exec(text);
  if (!match) throw new Error(`no :root rule in ${path}`);
  return text.slice(match.index);
}

describe("design tokens", () => {
  it("match the state admin's, byte for byte", () => {
    const dashboard = tokenBody("app/tokens.css");
    const stateAdmin = tokenBody("../state-admin/app/tokens.css");
    expect(dashboard).toBe(stateAdmin);
  });

  it("define the clinical colours both surfaces report against", () => {
    const body = tokenBody("app/tokens.css");
    for (const token of ["--severe", "--moderate", "--normal", "--reference"]) {
      expect(body).toContain(token);
    }
  });
});
