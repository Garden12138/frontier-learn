import { ApiError } from '../api/errors';

export function ErrorNotice({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof ApiError ? error.body.message : '请求未完成，请检查连接后重试。';
  return <div role="alert">
    <p>{message}</p>
    {error instanceof ApiError && error.body.request_id && <small>请求编号：{error.body.request_id}</small>}
    {onRetry && <button type="button" onClick={onRetry}>重试</button>}
  </div>;
}
