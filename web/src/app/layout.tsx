import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
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
        <header className="border-b border-[var(--border)] sticky top-0 z-20 backdrop-blur-sm bg-black/60">
          <div className="mx-auto max-w-7xl px-6 h-14 flex items-center justify-between">
            <Link href="/" className="flex items-center gap-2 group">
              <div className="w-5 h-5 rounded-sm bg-white group-hover:bg-[var(--accent)] transition-colors" />
              <span className="text-sm font-medium tracking-tight">squeeze finder</span>
              <span className="text-[11px] text-[var(--muted)] mono">v0.1</span>
            </Link>
            <nav className="flex items-center gap-6 text-sm text-[var(--muted)]">
              <Link href="/" className="hover:text-white transition-colors">scan</Link>
              <Link href="/0dte" className="hover:text-white transition-colors">0dte</Link>
              <Link href="/ideas" className="hover:text-white transition-colors">ideas</Link>
              <a
                href="http://127.0.0.1:8000/docs"
                target="_blank"
                rel="noreferrer"
                className="hover:text-white transition-colors"
              >
                api
              </a>
            </nav>
          </div>
        </header>
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
