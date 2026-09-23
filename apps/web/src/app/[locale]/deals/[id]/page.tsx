import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ApplicationShell } from "@/components/application-shell";
import { enabledLocales, isEnabledLocale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { DealWorkspaceClient } from "./deal-workspace-client";

type Props = {
  params: Promise<{ locale: string; id: string }>;
};

export function generateStaticParams() {
  return enabledLocales.map((locale) => ({ locale }));
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale, id } = await params;
  if (!isEnabledLocale(locale)) notFound();
  const messages = getMessages(locale);
  return {
    title: `${messages.dealWorkspace?.title ?? "فضای کاری معامله"} | ${id.slice(0, 8)}`,
    description: messages.dealWorkspace?.badges?.immutableNotice ?? "فضای کاری معامله تجاری و شرایط قطعی",
  };
}

export default async function DealWorkspacePage({ params }: Props) {
  const { locale, id } = await params;
  if (!isEnabledLocale(locale)) notFound();
  const messages = getMessages(locale);

  return (
    <ApplicationShell locale={locale} messages={messages.shell}>
      <DealWorkspaceClient locale={locale} dealId={id} />
    </ApplicationShell>
  );
}
