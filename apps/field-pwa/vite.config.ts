/// <reference types="vitest/config" />
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

/**
 * Section 4 specifies Vite + React, an installable PWA, a Workbox service
 * worker and an IndexedDB queue. Section 9.1 adds the constraint that shapes
 * every choice here: this runs on a three-year-old, roughly Rs 8,000 Android
 * phone, every day, on an intermittent connection.
 *
 * So: no UI framework, no animation library, no icon package, no CSS framework.
 * Everything is hand-rolled against CSS custom properties. That is not
 * minimalism for its own sake -- each dependency is bytes parsed on a slow CPU
 * before a worker can photograph a plate.
 */
export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "prompt",
      // "prompt" rather than "autoUpdate": a silent reload mid-capture would
      // lose whatever the worker had on screen. The update is offered instead.
      injectRegister: "auto",
      manifest: {
        name: "PoshanNetra - पोषण नेत्र",
        short_name: "पोषण नेत्र",
        description: "आंगनवाड़ी और आश्रम विद्यालय भोजन निगरानी / Meal monitoring for Anganwadi centres and Ashram schools",
        // Hindi first, per Section 9.1. The app language, not just the copy.
        lang: "hi-IN",
        dir: "ltr",
        start_url: "/",
        scope: "/",
        display: "standalone",
        orientation: "portrait",
        background_color: "#f8fafc",
        theme_color: "#0f172a",
        categories: ["health", "government", "productivity"],
        icons: [
          { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
          { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
          { src: "/icons/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
        ],
      },
      workbox: {
        globPatterns: ["**/*.{js,css,html,svg,png,woff2}"],
        // The app shell is precached so a cold start with no signal still
        // reaches the capture screen. API responses are deliberately NOT
        // cached here -- the IndexedDB layer in src/db owns that, because it
        // needs to survive a cache eviction that Workbox would happily perform.
        navigateFallback: "index.html",
        runtimeCaching: [
          {
            urlPattern: ({ url }) => url.pathname.startsWith("/api/"),
            handler: "NetworkOnly",
            options: {
              backgroundSync: {
                name: "poshannetra-captures",
                options: { maxRetentionTime: 60 * 24 * 7 },
              },
            },
          },
        ],
      },
      devOptions: { enabled: false },
    }),
  ],
  server: {
    port: 5173,
    proxy: {
      // The FastAPI backend from Phases 1-2.
      "/api": { target: "http://localhost:8000", changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, "") },
    },
  },
  build: {
    target: "es2018",
    // es2018 rather than the default: Android WebViews on cheap phones lag
    // well behind Chrome's release channel, and a syntax error there is a
    // blank screen with no way to report it.
    cssCodeSplit: false,
    reportCompressedSize: true,
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
    globals: true,
    css: false,
  },
});
