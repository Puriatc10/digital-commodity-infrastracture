import { ApplicationShell } from "@/components/application-shell";
import { getMessages } from "@/i18n/messages";
import { OrganizationProfileClient } from "./client";
import { Suspense } from "react";
import { Loader2 } from "lucide-react";
import { isEnabledLocale } from "@/i18n/config";
import { notFound } from "next/navigation";

export default async function OrganizationProfilePage({ params }: { params: Promise<{ locale: string, id: string }> }) {
  const { locale, id } = await params;
  if (!isEnabledLocale(locale)) notFound();

  const messages = getMessages(locale as "fa");

  return (
    <ApplicationShell locale={locale as "fa"} messages={messages.shell}>
      <div className="flex h-full flex-col gap-6 p-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">پروفایل شرکت</h1>
          <p className="text-muted-foreground">اطلاعات، نقش‌ها و تاییدیه‌های این شرکت.</p>
        </div>

        <Suspense fallback={<div className="flex items-center justify-center p-8"><Loader2 className="h-8 w-8 animate-spin text-primary" /></div>}>
           <OrganizationProfileClient id={id} />
        </Suspense>
      </div>
    </ApplicationShell>
  );
}
