import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/contexts/AuthContext";
import Navbar from "@/components/Navbar";

export const metadata: Metadata = {
  title: "AI Interview Bot",
  description: "AI-powered job interview simulator with real-time evaluation",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-slate-50">
        <AuthProvider>
          <Navbar />
          <main className="max-w-6xl mx-auto px-4 sm:px-6 py-8">{children}</main>
        </AuthProvider>
      </body>
    </html>
  );
}
