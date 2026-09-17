import { ApplicationShell } from "@/components/application-shell";
import { getMessages } from "@/i18n/messages";
import type { EnabledLocale } from "@/i18n/config";
import { OpportunityDeskClient } from "./client";

export default async function OpportunityDeskPage({
  params,
}: {
  params: Promise<{ locale: EnabledLocale }>;
}) {
  const { locale } = await params;
  const messages = getMessages(locale);

  return (
    <ApplicationShell locale={locale} messages={messages.shell}>
      <div className="flex h-full flex-col gap-6 p-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            {messages.opportunities.title}
          </h1>
          <p className="text-sm text-muted-foreground">
            {messages.opportunities.subtitle}
          </p>
        </div>

        <OpportunityDeskClient locale={locale} />
      </div>
    </ApplicationShell>
  );
}
