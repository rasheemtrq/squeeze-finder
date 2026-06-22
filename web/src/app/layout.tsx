import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "squeeze finder",
  description: "Short-squeeze scanner for US equities",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col surface-fade">
        <main className="flex-1">{children}</main>
        <footer className="border-t border-[var(--border)] py-6 px-6 text-xs text-[var(--muted)]">
          <div className="mx-auto max-w-7xl flex items-center justify-between">
            <span>free data · not investment advice · ideas not trades</span>
            <span className="mono">localhost</span>
          </div>
        </footer>
      </body>
    </html>
  );
}
