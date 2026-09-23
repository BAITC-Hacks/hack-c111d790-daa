export async function api<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(
    `/api${path}`,
    body === undefined
      ? undefined
      : {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        },
  );
  if (!response.ok) {
    let message = `Ошибка сервера (${response.status})`;
    try {
      const result = await response.json();
      message = Array.isArray(result.detail)
        ? result.detail
            .slice(0, 4)
            .map((d: { loc: string[]; msg: string }) => `${d.loc.join('.')}: ${d.msg}`)
            .join('; ')
        : result.detail || message;
    } catch {
      /* Non-JSON errors retain the status. */
    }
    throw new Error(message);
  }
  return response.json();
}
