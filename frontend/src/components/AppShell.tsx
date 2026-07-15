"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

import { useAuth } from "@/components/AuthProvider";

const navItems = [
  { href: "/orders", label: "Orders" },
  { href: "/moderation", label: "Moderation" },
  { href: "/sources", label: "Sources" },
  { href: "/keywords", label: "Keywords" },
  { href: "/statistics", label: "Statistics" }
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { session, isReady, logout } = useAuth();

  useEffect(() => {
    if (isReady && !session && pathname !== "/login") {
      router.replace("/login");
    }
  }, [isReady, pathname, router, session]);

  if (!isReady) {
    return <div className="page-message">Загрузка сессии...</div>;
  }

  if (!session && pathname !== "/login") {
    return <div className="page-message">Переход к login...</div>;
  }

  if (pathname === "/login") {
    return <>{children}</>;
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div>
          <h1>TG Order Radar</h1>
          <p className="muted">Admin MVP</p>
        </div>
        <nav>
          {navItems.map((item) => (
            <Link
              className={pathname === item.href ? "active nav-link" : "nav-link"}
              href={item.href}
              key={item.href}
            >
              {item.label}
            </Link>
          ))}
        </nav>
        <div className="sidebar-footer">
          <p className="muted">{session?.role}</p>
          <button className="secondary" onClick={logout} type="button">
            Выйти
          </button>
        </div>
      </aside>
      <main className="content">{children}</main>
    </div>
  );
}
