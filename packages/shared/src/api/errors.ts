import type { components } from './schema';

export type ApiErrorBody = components['schemas']['ErrorResponse'];

export class ApiError extends Error {
  constructor(public readonly status: number, public readonly body: ApiErrorBody) {
    super(body.message);
    this.name = 'ApiError';
  }
}
