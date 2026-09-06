import type { NextConfig } from "next";

const isolatedDistDir = process.env.RECOVERYOS_NEXT_DIST_DIR?.trim();

const nextConfig: NextConfig = {
  ...(isolatedDistDir ? { distDir: isolatedDistDir } : {}),
  // Vercel's adapter handles packaging; standalone expects traces it does not emit.
  output: process.env.VERCEL === "1" ? undefined : "standalone",
  poweredByHeader: false,
  reactStrictMode: true,
};

export default nextConfig;
