import { Suspense } from "react";
import { notFound } from "next/navigation";
import { Loader2 } from "lucide-react";

import { ApplicationShell } from "@/components/application-shell";
import { isEnabledLocale, type EnabledLocale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { TradeHubClient } from "./trade-hub-client";

export default async function TradeHubPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  if (!isEnabledLocale(locale)) notFound();

  const messages = getMessages(locale as EnabledLocale);

  return (
    <ApplicationShell locale={locale as EnabledLocale} messages={messages.shell}>
      <div className="flex h-full flex-col gap-6 p-6">
        <Suspense
          fallback={
            <div className="flex h-64 items-center justify-center">
              <Loader2 className="h-8 w-8 animate-spin text-primary" />
            </div>
          }
        >
          <TradeHubClient locale={locale as EnabledLocale} />
        </Suspense>
      </div>
    </ApplicationShell>
  );
}
