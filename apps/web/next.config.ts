import type { NextConfig } from "next";
import { defaultLocale } from "./src/i18n/config";

const nextConfig: NextConfig = {
  // Keep the repository's existing agent guidance authoritative.
  agentRules: false,
  turbopack: { root: __dirname },
  // Django owns API URL slash semantics; do not redirect its router endpoints.
  skipTrailingSlashRedirect: true,
  async rewrites() {
    const apiOrigin = process.env.API_PROXY_TARGET;
    return apiOrigin
      ? [
          { source: "/api/:path*/", destination: `${apiOrigin.replace(/\/$/, "")}/api/:path*/` },
          { source: "/api/:path*", destination: `${apiOrigin.replace(/\/$/, "")}/api/:path*` },
        ]
      : [];
  },
  async redirects() {
    return [{ source: "/", destination: `/${defaultLocale}`, permanent: false }];
  },
};

export default nextConfig;
