"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { defaultLocale, isEnabledLocale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";

export default function NotFound() {
  const params = useParams<{ locale: string }>();
  const locale = isEnabledLocale(params.locale) ? params.locale : defaultLocale;
  const messages = getMessages(locale).notFound;
  return (
    <main className="mx-auto max-w-xl px-6 py-24 text-center">
      <h1 className="text-2xl font-semibold">{messages.title}</h1>
      <p className="my-6 text-muted-foreground">{messages.description}</p>
      <Link href={`/${locale}`} className="text-primary underline underline-offset-4">{messages.back}</Link>
    </main>
  );
}
