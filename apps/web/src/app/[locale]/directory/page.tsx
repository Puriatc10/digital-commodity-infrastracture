import { ApplicationShell } from "@/components/application-shell";
import { getMessages } from "@/i18n/messages";
import { DirectoryClient } from "./client";
import { Suspense } from "react";
import { Loader2 } from "lucide-react";

export default async function DirectoryPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  const messages = getMessages(locale as "fa");

  return (
    <ApplicationShell locale={locale as "fa"} messages={messages.shell}>
      <div className="flex h-full flex-col gap-6 p-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{messages.directory.title}</h1>
          <p className="text-muted-foreground">{messages.directory.subtitle}</p>
        </div>

        <Suspense fallback={<div className="flex items-center justify-center p-8"><Loader2 className="h-8 w-8 animate-spin text-primary" /></div>}>
           <DirectoryClient />
        </Suspense>
      </div>
    </ApplicationShell>
  );
}
