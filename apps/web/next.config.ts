import type { NextConfig } from "next";
import { defaultLocale } from "./src/i18n/config";

const nextConfig: NextConfig = {
  // Keep the repository's existing agent guidance authoritative.
  agentRules: false,
  turbopack: { root: __dirname },
  async redirects() {
    return [{ source: "/", destination: `/${defaultLocale}`, permanent: false }];
  },
};

export default nextConfig;
