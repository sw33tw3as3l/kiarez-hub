import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "export",
  basePath: "/kiarez-hub",
  assetPrefix: "/kiarez-hub/",
  trailingSlash: true,
  images: { unoptimized: true },
};

export default nextConfig;
