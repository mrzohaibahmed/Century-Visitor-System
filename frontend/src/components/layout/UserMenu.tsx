"use client";

import Link from "next/link";
import { useState } from "react";

import { CHANGE_PASSWORD_PATH, useSession } from "@/components/session/SessionProvider";
import { Button } from "@/components/ui/Button";

const ROLE_LABELS = { ADMIN: "Administrator", GUARD: "Guard" } as const;

export function UserMenu() {
  const { user, signOut } = useSession();
  const [signingOut, setSigningOut] = useState(false);

  return (
    <div className="flex items-center gap-3">
      <div className="text-right leading-tight">
        <p className="text-sm font-semibold text-ink">{user.display_name || user.username}</p>
        <p className="text-xs text-ink-muted">{ROLE_LABELS[user.role]}</p>
      </div>
      <Link href={CHANGE_PASSWORD_PATH} className="rounded-lg px-3 py-2 text-sm text-ink-muted hover:bg-canvas hover:text-ink">
        Change password
      </Link>
      <Button
        variant="secondary"
        loading={signingOut}
        onClick={() => { setSigningOut(true); void signOut(); }}
      >
        Log out
      </Button>
    </div>
  );
}
