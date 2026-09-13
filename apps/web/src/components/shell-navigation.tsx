"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { EnabledLocale } from "@/i18n/config";
import type { Messages } from "@/i18n/messages";
import { useAuth } from "@/lib/auth-context";

export function ShellNavigation({
  locale,
  messages,
}: {
  locale: EnabledLocale;
  messages: Messages["shell"];
}) {
  const pathname = usePathname() || "";
  const { state } = useAuth();

  const isOperatorOrAdmin =
    state.status === "authenticated" &&
    state.systemRoles.some((r) => r === "operator" || r === "admin");

  const homeHref = `/${locale}`;
  const directoryHref = `/${locale}/directory`;
  const queueHref = `/${locale}/operator/verification`;

  const isHomeActive = pathname === homeHref;
  const isDirectoryActive = pathname.startsWith(directoryHref);
  const isQueueActive = pathname.startsWith(queueHref);

  const getLinkClasses = (isActive: boolean) =>
    isActive
      ? "flex min-h-11 items-center gap-3 rounded-md border border-primary/15 bg-accent px-4 py-3 text-sm font-medium text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
      : "flex min-h-11 items-center gap-3 rounded-md px-4 py-3 text-sm font-medium text-muted-foreground hover:bg-accent/50 hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring";

  return (
    <nav aria-label={messages.navigation} className="flex flex-col gap-1 px-4 pb-4 lg:py-4">
      <Link
        href={homeHref}
        aria-current={isHomeActive ? "page" : undefined}
        className={getLinkClasses(isHomeActive)}
      >
        {isHomeActive && <span aria-hidden="true" className="size-2 rounded-sm bg-primary" />}
        {messages.home}
      </Link>

      <Link
        href={directoryHref}
        aria-current={isDirectoryActive ? "page" : undefined}
        className={getLinkClasses(isDirectoryActive)}
      >
        {isDirectoryActive && <span aria-hidden="true" className="size-2 rounded-sm bg-primary" />}
        {messages.directory}
      </Link>

      {isOperatorOrAdmin && (
        <Link
          href={queueHref}
          aria-current={isQueueActive ? "page" : undefined}
          className={getLinkClasses(isQueueActive)}
        >
          {isQueueActive && <span aria-hidden="true" className="size-2 rounded-sm bg-primary" />}
          {messages.verificationQueue}
        </Link>
      )}
    </nav>
  );
}
