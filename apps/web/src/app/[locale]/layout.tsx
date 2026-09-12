import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { enabledLocales, isEnabledLocale, locales } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import "@fontsource/vazirmatn/arabic-400.css";
import "@fontsource/vazirmatn/arabic-500.css";
import "@fontsource/vazirmatn/arabic-600.css";
import "../globals.css";
import { AuthProvider } from "@/lib/auth-context";
import { Providers } from "@/components/providers";

type Props = {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
};

export function generateStaticParams() {
  return enabledLocales.map((locale) => ({ locale }));
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params;
  if (!isEnabledLocale(locale)) notFound();
  return getMessages(locale).metadata;
}

export default async function LocaleLayout({ children, params }: Props) {
  const { locale } = await params;
  if (!isEnabledLocale(locale)) notFound();

  return (
    <html lang={locale} dir={locales[locale].direction}>
      <body className="font-sans antialiased">
        <Providers><AuthProvider>{children}</AuthProvider></Providers>
      </body>
    </html>
  );
}
