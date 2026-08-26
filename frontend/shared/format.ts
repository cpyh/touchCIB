/** 全站统一的数字与时间格式化工具（唯一维护点）。
 *
 * 约定：
 * - percent：百分比，null → "—"
 * - compactMoney：大额压缩（¥12.34亿 / ¥1,234.5万 / 全量）
 * - exactMoney：全量两位小数（画像 AUM 等精确口径）
 * - money：全量取整（营销列表等展示口径）
 * - metric：指标小数位控制（AUC/F1 等）
 * - formatTime：短时间 "04-15 10:30"
 * - formatDateTime：完整本地化时间
 */

export function formatNumber(
  value: number | null | undefined,
  maximumFractionDigits = 0,
  minimumFractionDigits = 0
): string {
  return value == null
    ? "—"
    : value.toLocaleString("zh-CN", {
        minimumFractionDigits,
        maximumFractionDigits,
      });
}

export function percent(
  value: number | null | undefined,
  digits = 1
): string {
  return value == null ? "—" : `${(value * 100).toFixed(digits)}%`;
}

export function compactMoney(value: number | null | undefined): string {
  if (value == null) return "—";
  if (Math.abs(value) >= 100_000_000) {
    return `¥${formatNumber(value / 100_000_000, 2, 2)}亿`;
  }
  if (Math.abs(value) >= 10_000) {
    return `¥${formatNumber(value / 10_000, 1, 1)}万`;
  }
  return `¥${formatNumber(value, 2)}`;
}

export function exactMoney(value: number | null | undefined): string {
  return value == null
    ? "—"
    : `¥${formatNumber(value, 2, 2)}`;
}

export function money(value: number | null | undefined): string {
  return value == null
    ? "—"
    : `¥${formatNumber(value)}`;
}

export function metric(
  value: number | null | undefined,
  digits = 3
): string {
  return value == null ? "—" : value.toFixed(digits);
}

export function formatTime(value: string | null | undefined): string {
  if (!value) return "—";
  return value.replace("T", " ").slice(5, 16);
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString("zh-CN", {
        hour12: false,
      });
}
