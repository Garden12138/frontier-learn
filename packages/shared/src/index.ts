export const API_PREFIX = '/api/v1';
export { ApiClient } from './api/client';
export type { JobResponse, LoginResponse, UserResponse } from './api/client';
export type { SourceResponse, DocumentResponse, KnowledgeResponse, EvidenceResponse, CorrectionRequest, AuthOptions } from './api/client';
export type { GoalInput, GoalResponse, GoalUpdate, PlanResponse, PlanAction, PlanTask, RevisionSummary } from './api/client';
export type { PageSnapshot, AnalyzePageRequest, AskRequest, SessionResponse, SessionSummary, Guide } from './api/client';
export type { ImportConversationRequest, ConversationResponse, ConversationSummary, CandidateDecision } from './api/client';
export { GuideSession } from './ui/GuideSession';
export { ErrorNotice } from './ui/ErrorNotice';
export { ApiError } from './api/errors';
export type { ApiErrorBody } from './api/errors';

export interface Health {
  status: 'ok';
  service: 'frontier-learn';
  version: string;
}

// The complete authenticated client and generated domain types are tracked by T012.
export async function checkHealth(signal?: AbortSignal): Promise<Health> {
  const response = await fetch(`${API_PREFIX}/health`, signal ? { signal } : {});
  if (!response.ok) throw new Error('服务暂不可用，请稍后重试。');
  return response.json() as Promise<Health>;
}

export type { AssessmentResponse, ArtifactResponse, PreviewRequest } from './api/client';
export { AssessmentPanel, downloadMarkdown } from './ui/AssessmentPanel';

export type { SettingsResponse } from './api/client';

export { AccountForm } from './ui/AccountForm';
export type { AccountSession } from './api/client';
