import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { cookies } from "next/headers";

import { Toaster } from "@/components/ui/Toaster";
import { THEME_COOKIE, themeFrom } from "@/lib/theme";

import "./globals.css";

// Downloaded at build time and served by this app: the gate PCs never contact Google.
const inter = Inter({ subsets: ["latin"], display: "swap", variable: "--font-inter" });

export const metadata: Metadata = {
  title: { default: "Century Gate VMS", template: "%s · Century Gate VMS" },
  description: "Visitor management for gate and reception staff.",
  robots: { index: false, follow: false },
};

export default async function RootLayout({ children }: LayoutProps<"/">) {
  // The theme is rendered on the server from the cookie, so the first paint is already right.
  const theme = themeFrom((await cookies()).get(THEME_COOKIE)?.value);
  return (
    <html lang="en" data-theme={theme} className={`${inter.variable} h-full antialiased`}>
      <body className="min-h-full">
        {children}
        <Toaster />
      </body>
    </html>
  );
}
