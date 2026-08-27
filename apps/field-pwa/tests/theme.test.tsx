import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ThemeProvider, useTheme } from "../src/theme/ThemeProvider";
import { I18nProvider, useI18n } from "../src/i18n/I18nProvider";

/**
 * Theme and language state.
 *
 * Both persist to localStorage rather than to the server, because both must be
 * correct on a cold start with no signal. A worker who chose Hindi and the
 * sunlight theme yesterday should not open the app in English at default
 * contrast because they are standing in a field.
 */

function ThemeProbe() {
  const { theme, resolved, setTheme } = useTheme();
  return (
    <div>
      <span data-testid="theme">{theme}</span>
      <span data-testid="resolved">{resolved}</span>
      <button onClick={() => setTheme("sunlight")}>sunlight</button>
      <button onClick={() => setTheme("dark")}>dark</button>
      <button onClick={() => setTheme("system")}>system</button>
    </div>
  );
}

// Re-installed before every test: vi.restoreAllMocks() in the shared setup
// resets vi.fn() implementations, which would otherwise leave matchMedia
// returning undefined for the rest of the file.
beforeEach(() => mockPrefersDark(false));

function mockPrefersDark(dark: boolean) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: dark,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

describe("theme", () => {
  it("follows the phone by default", () => {
    render(<ThemeProvider><ThemeProbe /></ThemeProvider>);
    expect(screen.getByTestId("theme")).toHaveTextContent("system");
  });

  it("resolves system to dark when the phone is dark", () => {
    mockPrefersDark(true);
    render(<ThemeProvider><ThemeProbe /></ThemeProvider>);
    expect(screen.getByTestId("resolved")).toHaveTextContent("dark");
  });

  it("leaves the data-theme attribute off in system mode", () => {
    // Removing it hands control to the prefers-color-scheme block in
    // tokens.css, so exactly one place decides what gets painted.
    render(<ThemeProvider><ThemeProbe /></ThemeProvider>);
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
  });

  it("applies an explicit choice to the document", async () => {
    render(<ThemeProvider><ThemeProbe /></ThemeProvider>);
    await userEvent.click(screen.getByText("sunlight"));
    expect(document.documentElement.getAttribute("data-theme")).toBe("sunlight");
  });

  it("persists the choice across a reload", async () => {
    const { unmount } = render(<ThemeProvider><ThemeProbe /></ThemeProvider>);
    await userEvent.click(screen.getByText("sunlight"));
    unmount();
    render(<ThemeProvider><ThemeProbe /></ThemeProvider>);
    expect(screen.getByTestId("theme")).toHaveTextContent("sunlight");
  });

  it("keeps an explicit light choice even when the phone goes dark", async () => {
    // A phone flipping to dark at dusk must not override a worker who is still
    // standing outside in the light.
    mockPrefersDark(true);
    render(<ThemeProvider><ThemeProbe /></ThemeProvider>);
    await userEvent.click(screen.getByText("sunlight"));
    expect(screen.getByTestId("resolved")).toHaveTextContent("sunlight");
  });

  it("can be switched back to following the phone", async () => {
    render(<ThemeProvider><ThemeProbe /></ThemeProvider>);
    await userEvent.click(screen.getByText("dark"));
    await userEvent.click(screen.getByText("system"));
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
  });

  it("updates the browser theme-color to match", async () => {
    const meta = document.createElement("meta");
    meta.name = "theme-color";
    document.head.appendChild(meta);
    render(<ThemeProvider><ThemeProbe /></ThemeProvider>);
    await userEvent.click(screen.getByText("dark"));
    expect(meta.content).toBe("#0b1220");
    meta.remove();
  });

  it("survives localStorage being unavailable", () => {
    // Private browsing, or storage disabled by policy. A dead toggle is worse
    // than a non-persistent one.
    const getItem = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    expect(() => render(<ThemeProvider><ThemeProbe /></ThemeProvider>)).not.toThrow();
    getItem.mockRestore();
  });
});

function LangProbe() {
  const { lang, setLang, t, alt } = useI18n();
  return (
    <div>
      <span data-testid="lang">{lang}</span>
      <span data-testid="label">{t("navHome")}</span>
      <span data-testid="alt">{alt("navHome")}</span>
      <button onClick={() => setLang("en")}>english</button>
    </div>
  );
}

describe("language", () => {
  it("starts in Hindi regardless of the phone locale", () => {
    // Section 9.1: Hindi primary, English secondary -- not the reverse. A
    // worker on an English-locale phone still opens the app in Hindi.
    render(<I18nProvider><LangProbe /></I18nProvider>);
    expect(screen.getByTestId("lang")).toHaveTextContent("hi");
    expect(screen.getByTestId("label")).toHaveTextContent("मुख्य");
  });

  it("exposes the other language for secondary captions", () => {
    render(<I18nProvider><LangProbe /></I18nProvider>);
    expect(screen.getByTestId("alt")).toHaveTextContent("Home");
  });

  it("switches without a network round-trip", async () => {
    // Both languages ship in the bundle; a toggle that needed the network
    // would be useless in exactly the situation it is most needed.
    render(<I18nProvider><LangProbe /></I18nProvider>);
    await userEvent.click(screen.getByText("english"));
    expect(screen.getByTestId("label")).toHaveTextContent("Home");
  });

  it("persists across a reload", async () => {
    const { unmount } = render(<I18nProvider><LangProbe /></I18nProvider>);
    await userEvent.click(screen.getByText("english"));
    unmount();
    render(<I18nProvider><LangProbe /></I18nProvider>);
    expect(screen.getByTestId("lang")).toHaveTextContent("en");
  });

  it("keeps document.lang in step for screen readers and font selection", async () => {
    render(<I18nProvider><LangProbe /></I18nProvider>);
    expect(document.documentElement.lang).toBe("hi");
    await act(async () => {
      await userEvent.click(screen.getByText("english"));
    });
    expect(document.documentElement.lang).toBe("en");
  });
});
