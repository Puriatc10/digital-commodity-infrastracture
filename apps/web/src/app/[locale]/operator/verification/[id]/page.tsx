"use client";

import { ApplicationShell } from "@/components/application-shell";
import { getMessages } from "@/i18n/messages";
import { VerificationCaseDetailClient } from "./client";
import { useParams } from "next/navigation";
import type { EnabledLocale } from "@/i18n/config";

export default function VerificationCaseDetailPage() {
  const routeParams = useParams();
  const organizationId = (routeParams?.id as string) || "test-org-id";
  const locale = ((routeParams?.locale as string) || "fa") as EnabledLocale;
  const messages = getMessages(locale);

  return (
    <ApplicationShell locale={locale} messages={messages.shell}>
      <div className="flex h-full flex-col gap-6 p-6">
        <VerificationCaseDetailClient id={organizationId} locale={locale} />
      </div>
    </ApplicationShell>
  );
}
