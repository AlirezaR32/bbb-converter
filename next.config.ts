import type { NextConfig } from "next";

const BACKEND_ORIGIN = process.env.BACKEND_ORIGIN ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  typescript: {
    ignoreBuildErrors: true,
  },
  reactStrictMode: false,
  async rewrites() {
    // Proxy the FastAPI backend on the same origin (no CORS, SSE passes through).
    return [
      {
        source: "/api/:path*",
        destination: `${BACKEND_ORIGIN}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
