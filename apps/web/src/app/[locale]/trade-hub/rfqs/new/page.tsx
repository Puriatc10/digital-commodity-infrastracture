import { ApplicationShell } from "@/components/application-shell";
import { isEnabledLocale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { notFound } from "next/navigation";
import { RFQBuilderClient } from "./rfq-builder-client";
import { Suspense } from "react";
import { Loader2 } from "lucide-react";

export default async function NewRFQPage({
  params,
  searchParams,
}: {
  params: Promise<{ locale: string }>;
  searchParams: Promise<{ draft?: string; id?: string }>;
}) {
  const { locale } = await params;
  if (!isEnabledLocale(locale)) notFound();

  const { draft, id } = await searchParams;
  const initialRfqId = draft || id;
  const messages = getMessages(locale);

  return (
    <ApplicationShell locale={locale} messages={messages.shell}>
      <div className="flex h-full flex-col gap-6 p-6">
        <Suspense
          fallback={
            <div className="flex h-64 items-center justify-center">
              <Loader2 className="h-8 w-8 animate-spin text-primary" />
            </div>
          }
        >
          <RFQBuilderClient locale={locale} initialRfqId={initialRfqId} />
        </Suspense>
      </div>
    </ApplicationShell>
  );
}
