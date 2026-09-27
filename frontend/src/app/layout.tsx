import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "Century Gate VMS", template: "%s · Century Gate VMS" },
  description: "Visitor management for gate and reception staff.",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full">{children}</body>
    </html>
  );
}
