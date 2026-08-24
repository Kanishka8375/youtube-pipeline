import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Anime Pipeline Control",
  description: "Operations surface for the serialized anime production pipeline."
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
