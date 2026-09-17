import { ApplicationShell } from "@/components/application-shell";
import { getMessages } from "@/i18n/messages";
import type { EnabledLocale } from "@/i18n/config";
import { OpportunityDetailClient } from "./client";

export default async function OpportunityDetailPage({
  params,
}: {
  params: Promise<{ locale: EnabledLocale; id: string }>;
}) {
  const { locale, id } = await params;
  const messages = getMessages(locale);

  return (
    <ApplicationShell locale={locale} messages={messages.shell}>
      <div className="flex h-full flex-col gap-6 p-6">
        <OpportunityDetailClient locale={locale} opportunityId={id} />
      </div>
    </ApplicationShell>
  );
}
