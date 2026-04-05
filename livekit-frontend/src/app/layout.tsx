import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Unmute LiveKit - Voice AI with Function Calling",
  description: "Voice assistant powered by LiveKit, Kyutai STT/TTS, and Qwen LLM",
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
