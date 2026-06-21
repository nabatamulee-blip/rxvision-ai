import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "RxVision AI",
  description: "Prescription Interpreter for Pharmacists",
  manifest: "/manifest.json",
  themeColor: "#0284c7",
  appleWebApp: {
    capable: true,
    statusBarStyle: "default",
    title: "RxVision AI",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
