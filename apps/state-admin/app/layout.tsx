import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "PoshanNetra — राज्य स्तरीय समीक्षा | State Review",
  description:
    "Child nutrition monitoring across Anganwadi centres and Ashram schools in the Banswara–Dungarpur belt, Rajasthan.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        {/* IBM Plex, including the Devanagari cut. Loaded with display=swap so
            the page paints immediately on a slow conference-room connection
            rather than showing invisible text. */}
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans+Devanagari:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
