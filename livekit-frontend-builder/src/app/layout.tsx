import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "NEMT Voice Assistant - Ride Booking",
  description: "Interactive Voice Agent for NEMT ride booking powered by LiveKit",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body suppressHydrationWarning>{children}</body>
    </html>
  );
}
