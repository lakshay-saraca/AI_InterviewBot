"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/contexts/AuthContext";

interface NavLink {
  href: string;
  label: string;
  adminOnly?: boolean;
}

const NAV_LINKS: NavLink[] = [
  { href: "/interview/mode-select", label: "Text Interview" },
  { href: "/interview/voice/start", label: "Voice Interview" },
  { href: "/admin/history", label: "History", adminOnly: true },
];

export default function Navbar() {
  const { user, isAdmin, logout } = useAuth();
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);

  const visibleLinks = NAV_LINKS.filter((link) => !link.adminOnly || isAdmin);

  const isActive = (href: string) => {
    if (href === "/interview/mode-select") {
      return pathname.startsWith("/interview") && !pathname.startsWith("/interview/voice");
    }
    if (href === "/interview/voice/start") {
      return pathname.startsWith("/interview/voice");
    }
    return pathname.startsWith(href);
  };

  return (
    <nav className="bg-white border-b border-slate-200">
      <div className="max-w-6xl mx-auto px-4 sm:px-6">
        <div className="flex items-center justify-between h-14">
          <div className="flex items-center gap-8">
            <Link href="/" className="text-lg font-bold text-slate-900 shrink-0">
              AI Interview Bot
            </Link>

            {user && (
              <div className="hidden md:flex items-center gap-1">
                {visibleLinks.map((link) => (
                  <Link
                    key={link.href}
                    href={link.href}
                    className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                      isActive(link.href)
                        ? "bg-blue-50 text-blue-700"
                        : "text-slate-600 hover:text-slate-900 hover:bg-slate-50"
                    }`}
                  >
                    {link.label}
                  </Link>
                ))}
              </div>
            )}
          </div>

          <div className="flex items-center gap-3">
            {user ? (
              <>
                <span className="hidden sm:inline text-sm text-slate-500">
                  {user.name}
                </span>
                {isAdmin && (
                  <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-violet-100 text-violet-700">
                    Admin
                  </span>
                )}
                <button
                  onClick={logout}
                  className="text-sm text-slate-500 hover:text-slate-700 transition-colors"
                >
                  Sign out
                </button>
              </>
            ) : (
              <Link
                href="/login"
                className="text-sm font-medium text-blue-600 hover:text-blue-700 transition-colors"
              >
                Sign in
              </Link>
            )}

            {user && (
              <button
                onClick={() => setMobileOpen(!mobileOpen)}
                className="md:hidden p-1.5 rounded-md text-slate-500 hover:bg-slate-50"
                aria-label="Toggle menu"
              >
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  {mobileOpen ? (
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  ) : (
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
                  )}
                </svg>
              </button>
            )}
          </div>
        </div>

        {mobileOpen && user && (
          <div className="md:hidden border-t border-slate-100 py-2 pb-3">
            {visibleLinks.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                onClick={() => setMobileOpen(false)}
                className={`block px-3 py-2 rounded-md text-sm font-medium ${
                  isActive(link.href)
                    ? "bg-blue-50 text-blue-700"
                    : "text-slate-600 hover:bg-slate-50"
                }`}
              >
                {link.label}
              </Link>
            ))}
          </div>
        )}
      </div>
    </nav>
  );
}
