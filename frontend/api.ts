export async function api<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(
    `/api${path}`,
    body === undefined
      ? undefined
      : {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-WareSync-Request': '1' },
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
    if (response.status === 401 && !['/auth/login', '/auth/register', '/auth/me'].includes(path)) {
      window.dispatchEvent(new Event('waresync:session-expired'));
    }
    throw new ApiError(message, response.status);
  }
  return response.json();
}
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}
