import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  output: 'export',  // 静态导出
  distDir: 'dist',   // 输出目录
  trailingSlash: true,
  images: {
    unoptimized: true,
  },
};

export default nextConfig;
