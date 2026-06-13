"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/contexts/AuthContext";

interface AdminGuardProps {
  children: React.ReactNode;
}

export default function AdminGuard({ children }: AdminGuardProps) {
  const { user, isAdmin } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!user) {
      router.replace("/login");
    } else if (!isAdmin) {
      router.replace("/");
    }
  }, [user, isAdmin, router]);

  if (!user || !isAdmin) {
    return (
      <div className="flex items-center justify-center min-h-[50vh]">
        <p className="text-slate-500 text-sm">Checking access...</p>
      </div>
    );
  }

  return <>{children}</>;
}
