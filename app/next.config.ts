import type { NextConfig } from "next";

const BACKEND_URL = process.env.INTERNAL_API_URL || "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() {
    return {
      beforeFiles: [],
      afterFiles: [],
      fallback: [
        {
          source: "/api/:path*",
          destination: `${BACKEND_URL}/api/:path*`,
        },
      ],
    };
  },
};

export default nextConfig;
