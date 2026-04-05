import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Unmute LiveKit MCP - Voice AI with MCP Tool Calling",
  description: "Voice assistant powered by LiveKit, Kyutai STT/TTS, Qwen LLM, and MCP",
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
