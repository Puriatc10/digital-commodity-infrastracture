import { ApplicationShell } from "@/components/application-shell";
import { isEnabledLocale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { notFound } from "next/navigation";
import { SupplyListingBuilderClient } from "../../new/supply-listing-builder-client";
import { Suspense } from "react";
import { Loader2 } from "lucide-react";

export default async function EditSupplyListingPage({
  params,
}: {
  params: Promise<{ locale: string; id: string }>;
}) {
  const { locale, id } = await params;
  if (!isEnabledLocale(locale)) notFound();

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
          <SupplyListingBuilderClient locale={locale} initialListingId={id} />
        </Suspense>
      </div>
    </ApplicationShell>
  );
}
