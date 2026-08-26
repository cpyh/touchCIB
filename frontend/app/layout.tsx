import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "智能财富管理运营平台",
  description: "客户画像、营销策略与智能投顾一体化运营演示平台",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
