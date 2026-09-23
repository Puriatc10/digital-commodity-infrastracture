import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ApplicationShell } from "@/components/application-shell";
import { enabledLocales, isEnabledLocale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { DealsListClient } from "./deals-list-client";

type Props = {
  params: Promise<{ locale: string }>;
};

export function generateStaticParams() {
  return enabledLocales.map((locale) => ({ locale }));
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params;
  if (!isEnabledLocale(locale)) notFound();
  const messages = getMessages(locale);
  return {
    title: messages.dealsList?.title ?? "معاملات تجاری",
    description: messages.dealsList?.subtitle ?? "فهرست معاملات نهایی‌شده",
  };
}

export default async function DealsListPage({ params }: Props) {
  const { locale } = await params;
  if (!isEnabledLocale(locale)) notFound();
  const messages = getMessages(locale);

  return (
    <ApplicationShell locale={locale} messages={messages.shell}>
      <DealsListClient locale={locale} />
    </ApplicationShell>
  );
}
