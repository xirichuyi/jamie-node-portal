export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
export async function api<T>(path: string, data?: unknown): Promise<T> {
  const options: RequestInit = {
    method: data === undefined ? 'GET' : 'POST',
    credentials: 'same-origin',
    headers:
      data === undefined
        ? {}
        : { 'Content-Type': 'application/json', 'X-Jamie-Request': '1' },
    body: data === undefined ? undefined : JSON.stringify(data),
  };
  let response: Response | undefined;
  const signal = AbortSignal.timeout(25000);
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      response = await fetch('/api/' + path, { ...options, signal });
      if (
        data === undefined &&
        [502, 503, 504].includes(response.status) &&
        attempt < 2
      ) {
        await response.body?.cancel();
        await new Promise((resolve) =>
          setTimeout(resolve, 500 * (attempt + 1)),
        );
        continue;
      }
      break;
    } catch {
      if (data !== undefined || attempt === 2 || signal.aborted)
        throw new ApiError(
          0,
          data === undefined
            ? '暂时无法连接，请稍后重试。'
            : '连接中断，操作结果尚未确认。请先刷新查看状态，再决定是否重试。',
        );
      await new Promise((resolve) => setTimeout(resolve, 500 * (attempt + 1)));
    }
  }
  if (!response) throw new ApiError(0, '暂时无法连接，请稍后重试。');
  let result: T & { error?: string };
  try {
    result = await response.json();
  } catch {
    throw new ApiError(
      response.status,
      response.status === 429
        ? '操作过于频繁，请稍后重试。'
        : '服务暂时不可用，请稍后重试。',
    );
  }
  if (!result || typeof result !== 'object')
    throw new ApiError(response.status, '暂时无法读取数据，请刷新重试。');
  if (!response.ok)
    throw new ApiError(response.status, result.error || '请求失败');
  return result;
}
