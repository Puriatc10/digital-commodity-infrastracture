import type { ReactNode } from "react";
import type { EnabledLocale } from "@/i18n/config";
import type { Messages } from "@/i18n/messages";
import { getMessages } from "@/i18n/messages";
import { AuthStatusBar } from "./auth-status-bar";
import { DemoPersonaSwitcher } from "./demo-persona-switcher";
import { ShellNavigation } from "./shell-navigation";


export function ApplicationShell({
  children,
  locale,
  messages,
}: {
  children: ReactNode;
  locale: EnabledLocale;
  messages: Messages["shell"];
}) {
  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[16rem_minmax(0,1fr)]">
      <a href="#main-content" className="sr-only rounded-md bg-primary p-3 text-primary-foreground focus:not-sr-only focus:fixed focus:start-4 focus:top-4 focus:z-50">
        {messages.skipToContent}
      </a>
      <aside className="flex flex-col border-b border-border bg-card lg:min-h-screen lg:border-e lg:border-b-0">
        <div className="flex items-center gap-3 p-6 lg:py-8">
          <div aria-hidden="true" className="grid size-10 shrink-0 grid-cols-2 gap-1 rounded-lg bg-primary p-2.5">
            <span className="rounded-xs bg-white" />
            <span className="rounded-xs bg-white/50" />
            <span className="col-span-2 rounded-xs bg-white/80" />
          </div>
          <div>
            <p className="text-sm font-semibold">{messages.brand}</p>
            <p className="mt-1 text-xs text-muted-foreground">{messages.subtitle}</p>
          </div>
        </div>
        <ShellNavigation locale={locale} messages={messages} />
        <p className="mt-auto hidden px-6 py-6 text-xs text-muted-foreground lg:block">{messages.footer}</p>
      </aside>
      <div className="min-w-0">
        <header className="flex min-h-20 flex-wrap items-center justify-between gap-3 border-b border-border bg-card/70 px-6 lg:px-10">
          <p className="text-sm font-medium">{messages.home}</p>
          <DemoPersonaSwitcher messages={getMessages(locale).session} />
          <AuthStatusBar messages={getMessages(locale).session} />
          <div className="flex items-center gap-3 text-xs">
            <span className="text-muted-foreground">{messages.locale}</span>
            <span className="rounded-md border border-border bg-card px-3 py-1.5 text-muted-foreground">{messages.preview}</span>
          </div>
        </header>
        <main id="main-content" tabIndex={-1} className="mx-auto max-w-6xl px-6 py-10 outline-none lg:px-10 lg:py-14">
          {children}
        </main>
      </div>
    </div>
  );
}
