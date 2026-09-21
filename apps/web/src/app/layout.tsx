import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL("https://typesafe.pro"),
  title: "typesafe.pro - Messy words. Clear decisions.",
  description:
    "Turn text into labels, scores, and yes-or-no probabilities with free access to TypeSafe Jev. Try examples in your browser, then copy the code into your app.",
  alternates: {
    canonical: "/",
  },
  openGraph: {
    type: "website",
    url: "https://typesafe.pro/",
    title: "typesafe.pro - Messy words. Clear decisions.",
    description: "Small AI decisions, without the setup. Explore free Jev examples, try the playground, and take the code with you.",
  },
  twitter: {
    card: "summary",
    title: "typesafe.pro - Messy words. Clear decisions.",
    description: "Small AI decisions, without the setup. Explore free Jev examples, try the playground, and take the code with you.",
  },
  manifest: "/site.webmanifest",
  icons: {
    icon: [
      { url: "/favicon.ico", sizes: "any" },
      { url: "/favicon-16x16.png", sizes: "16x16", type: "image/png" },
      { url: "/favicon-32x32.png", sizes: "32x32", type: "image/png" },
    ],
    apple: [{ url: "/apple-touch-icon.png", sizes: "180x180", type: "image/png" }],
  },
};

function ThemeScript() {
  const source = `(() => {
  let preference = "system";
  try {
    const saved = localStorage.getItem("typesafe-pro-theme");
    if (["light", "dark", "system"].includes(saved)) preference = saved;
  } catch {}
  const dark = preference === "dark" || (preference === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  document.documentElement.dataset.themePreference = preference;
  const themeColor = document.querySelector("#theme-color");
  if (themeColor) themeColor.content = dark ? "#101b27" : "#ebf5ff";
})();`;
  return <script dangerouslySetInnerHTML={{ __html: source }} />;
}

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en" data-theme="light">
      <head>
        <meta id="theme-color" name="theme-color" content="#ebf5ff" />
        <meta name="color-scheme" content="light dark" />
        <meta name="referrer" content="strict-origin-when-cross-origin" />
        <ThemeScript />
      </head>
      <body>{children}</body>
    </html>
  );
}
