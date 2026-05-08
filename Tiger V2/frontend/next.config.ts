import type { NextConfig } from "next";

const API_UPSTREAM =
  process.env.NEXT_DEV_API_UPSTREAM ?? "https://100-48-88-95.sslip.io";

const nextConfig: NextConfig = {
  // Static export for production deploy on EC2 (served by nginx).
  // ``output: "export"`` ignores rewrites at build time but still honours
  // them when running ``next dev``, which is what we need: the dev server
  // proxies /api/* to the EC2 backend so the browser sees same-origin
  // requests, which is required for HttpOnly session cookies to actually
  // stick across modern browsers (Chrome's third-party-cookie policy
  // blocks cross-site Set-Cookie even with SameSite=None;Secure).
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },

  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${API_UPSTREAM}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
