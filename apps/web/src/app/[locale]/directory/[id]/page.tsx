import { ApplicationShell } from "@/components/application-shell";
import { getMessages } from "@/i18n/messages";
import { ProfileClient } from "./client";
import { Suspense } from "react";
import { Loader2 } from "lucide-react";

export default async function ProfilePage({ params }: { params: Promise<{ locale: string, id: string }> }) {
  const { locale, id } = await params;
  const messages = getMessages(locale as "fa");

  return (
    <ApplicationShell locale={locale as "fa"} messages={messages.shell}>
      <div className="flex h-full flex-col gap-6 p-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">پروفایل شرکت</h1>
        </div>
        <Suspense fallback={<div className="flex items-center justify-center p-8"><Loader2 className="h-8 w-8 animate-spin text-primary" /></div>}>
           <ProfileClient id={id} />
        </Suspense>
      </div>
    </ApplicationShell>
  );
}
