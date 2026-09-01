import type { NextConfig } from "next";

const isolatedDistDir = process.env.RECOVERYOS_NEXT_DIST_DIR?.trim();

const nextConfig: NextConfig = {
  ...(isolatedDistDir ? { distDir: isolatedDistDir } : {}),
  output: "standalone",
  poweredByHeader: false,
  reactStrictMode: true,
};

export default nextConfig;
