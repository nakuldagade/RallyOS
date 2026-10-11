import type { Metadata } from "next";
import AppShell from "@/components/AppShell";
import Providers from "@/components/Providers";
import "./globals.css";

export const metadata: Metadata = {
  title: "RallyOS",
  description: "One phone. Any court. Every rally counted.",
};

// Apply the saved theme before first paint (dark by default).
const themeScript = `try{var t=localStorage.getItem('rallyos-theme');document.documentElement.classList.toggle('dark',t!=='light')}catch(e){document.documentElement.classList.add('dark')}`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="min-h-screen antialiased">
        <Providers>
          <AppShell>{children}</AppShell>
        </Providers>
      </body>
    </html>
  );
}
