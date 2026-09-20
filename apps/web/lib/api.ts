import 'server-only';
export async function api<T>(path: string): Promise<T> {
  const response = await fetch(
    `${process.env.API_INTERNAL_URL || 'http://127.0.0.1:8000'}/api/v1${path}`,
    { cache: 'no-store', signal: AbortSignal.timeout(8000) },
  );
  if (!response.ok)
    throw new Error(
      response.status === 404 ? 'NOT_FOUND' : 'Data is temporarily unavailable. Please try again.',
    );
  return response.json() as Promise<T>;
}
