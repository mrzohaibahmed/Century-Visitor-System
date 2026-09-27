"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import type { Role } from "@/lib/api/auth";
import { navItemsFor } from "@/lib/navigation";

export function Sidebar({ role }: { role: Role }) {
  const pathname = usePathname();
  return (
    <nav aria-label="Main" className="flex w-60 shrink-0 flex-col bg-brand-900 text-white">
      <div className="px-5 py-5">
        <p className="text-sm font-bold tracking-wide">CENTURY GATE</p>
        <p className="text-xs text-white/60">Visitor Management</p>
      </div>
      <ul className="flex-1 space-y-1 px-3">
        {navItemsFor(role).map((item) => {
          const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
          return (
            <li key={item.href}>
              <Link
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={`block rounded-lg px-3 py-2.5 text-sm font-medium ${
                  active ? "bg-brand-600 text-white" : "text-white/75 hover:bg-white/10 hover:text-white"
                }`}
              >
                {item.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
