"use client";

import { ApplicationShell } from "@/components/application-shell";
import { getMessages } from "@/i18n/messages";
import { VerificationQueueClient } from "./client";
import { useParams } from "next/navigation";
import type { EnabledLocale } from "@/i18n/config";

export default function VerificationQueuePage() {
  const routeParams = useParams();
  const locale = ((routeParams?.locale as string) || "fa") as EnabledLocale;
  const messages = getMessages(locale);

  return (
    <ApplicationShell locale={locale} messages={messages.shell}>
      <div className="flex h-full flex-col gap-6 p-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{messages.verification.queue.title}</h1>
          <p className="text-muted-foreground">
            {messages.verification.queue.subtitle}
          </p>
        </div>

        <VerificationQueueClient locale={locale} />
      </div>
    </ApplicationShell>
  );
}
