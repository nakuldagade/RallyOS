import type { Metadata } from "next";
import Nav from "@/components/Nav";
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
        <div className="flex min-h-screen flex-col md:flex-row">
          <Nav />
          <main className="min-w-0 flex-1 px-4 py-6 md:px-8">{children}</main>
        </div>
      </body>
    </html>
  );
}
