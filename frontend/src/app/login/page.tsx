"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth, type UserRole } from "@/contexts/AuthContext";

const ADMIN_PASSPHRASE = process.env.NEXT_PUBLIC_ADMIN_PASSPHRASE ?? "admin";

export default function LoginPage() {
  const router = useRouter();
  const { login } = useAuth();
  const [name, setName] = useState("");
  const [role, setRole] = useState<UserRole>("candidate");
  const [passphrase, setPassphrase] = useState("");
  const [error, setError] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (!name.trim()) {
      setError("Please enter your name.");
      return;
    }

    if (role === "admin" && passphrase !== ADMIN_PASSPHRASE) {
      setError("Invalid admin passphrase.");
      return;
    }

    login(name.trim(), role);
    router.push("/");
  };

  return (
    <div className="flex flex-col items-center justify-center min-h-[70vh]">
      <div className="w-full max-w-md">
        <h1 className="text-2xl font-bold text-slate-900 mb-6 text-center">
          Sign In
        </h1>
        <form onSubmit={handleSubmit} className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm space-y-5">
          <div>
            <label htmlFor="name" className="block text-sm font-medium text-slate-700 mb-1">
              Name
            </label>
            <input
              id="name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              placeholder="Your name"
              autoFocus
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-2">
              Role
            </label>
            <div className="grid grid-cols-2 gap-3">
              <button
                type="button"
                onClick={() => setRole("candidate")}
                className={`px-4 py-3 rounded-lg border text-sm font-medium transition-colors ${
                  role === "candidate"
                    ? "border-blue-500 bg-blue-50 text-blue-700"
                    : "border-slate-200 text-slate-600 hover:bg-slate-50"
                }`}
              >
                Candidate
              </button>
              <button
                type="button"
                onClick={() => setRole("admin")}
                className={`px-4 py-3 rounded-lg border text-sm font-medium transition-colors ${
                  role === "admin"
                    ? "border-violet-500 bg-violet-50 text-violet-700"
                    : "border-slate-200 text-slate-600 hover:bg-slate-50"
                }`}
              >
                Admin
              </button>
            </div>
          </div>

          {role === "admin" && (
            <div>
              <label htmlFor="passphrase" className="block text-sm font-medium text-slate-700 mb-1">
                Admin Passphrase
              </label>
              <input
                id="passphrase"
                type="password"
                value={passphrase}
                onChange={(e) => setPassphrase(e.target.value)}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500 focus:border-transparent"
                placeholder="Enter admin passphrase"
              />
            </div>
          )}

          {error && (
            <p className="text-sm text-red-600">{error}</p>
          )}

          <button
            type="submit"
            className="w-full bg-blue-600 hover:bg-blue-700 text-white font-semibold py-3 rounded-lg transition-colors"
          >
            Continue
          </button>
        </form>
      </div>
    </div>
  );
}
