import { notFound } from "next/navigation";
import { ApplicationShell } from "@/components/application-shell";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { isEnabledLocale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";

export default async function FoundationPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  if (!isEnabledLocale(locale)) notFound();
  const messages = getMessages(locale);
  const content = messages.foundation;
  const details = [
    { title: content.languageTitle, description: content.languageDescription },
    { title: content.layoutTitle, description: content.layoutDescription },
    { title: content.scopeTitle, description: content.scopeDescription },
  ];

  return (
    <ApplicationShell locale={locale} messages={messages.shell}>
      <div className="mb-9 max-w-2xl">
        <p className="mb-3 text-sm font-medium text-primary">{content.eyebrow}</p>
        <h1 className="text-2xl font-semibold leading-relaxed tracking-tight sm:text-3xl">{content.title}</h1>
        <p className="mt-4 text-sm leading-8 text-muted-foreground sm:text-base">{content.description}</p>
      </div>
      <Card className="mb-6 border-s-4 border-s-primary shadow-none">
        <CardContent className="flex flex-col items-start gap-5 sm:flex-row sm:items-center sm:justify-between">
          <p className="max-w-xl text-sm leading-8">{content.notice}</p>
          <Button asChild variant="outline">
            <a href="#about">{content.action}</a>
          </Button>
        </CardContent>
      </Card>
      <Card id="about" className="scroll-mt-6 shadow-none">
        <CardHeader>
          <CardTitle>{content.aboutTitle}</CardTitle>
          <CardDescription>{content.aboutDescription}</CardDescription>
        </CardHeader>
        <CardContent>
          <dl className="divide-y divide-border">
            {details.map((detail) => (
              <div key={detail.title} className="grid gap-2 py-5 first:pt-0 last:pb-0 sm:grid-cols-[10rem_minmax(0,1fr)] sm:gap-8">
                <dt className="text-sm font-medium">{detail.title}</dt>
                <dd className="text-sm leading-7 text-muted-foreground">{detail.description}</dd>
              </div>
            ))}
          </dl>
        </CardContent>
      </Card>
    </ApplicationShell>
  );
}
