export const API_BASE = (
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:5001"
).replace(/\/$/, "");

/** 调用 Flask 接口，并把后端 error 字段转换成页面可读错误。 */
export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();

  if (!response.ok) {
    throw new Error(data?.error || `请求失败（HTTP ${response.status}）`);
  }
  return data as T;
}
