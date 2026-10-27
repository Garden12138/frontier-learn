import { ApiError } from './errors';
import type { components } from './schema';

export type UserResponse = components['schemas']['UserResponse'];
export type LoginResponse = components['schemas']['LoginResponse'];
export type JobResponse = components['schemas']['JobResponse'];
export type SourceResponse = components['schemas']['SourceResponse'];
export type DocumentResponse = components['schemas']['DocumentResponse'];
export type KnowledgeResponse = components['schemas']['KnowledgeResponse'];
export type EvidenceResponse = components['schemas']['EvidenceResponse'];
export type CorrectionRequest = components['schemas']['CorrectionRequest'];
export type AuthOptions = components['schemas']['AuthOptions'];
export type GoalInput = components['schemas']['GoalInput'];
export type GoalResponse = components['schemas']['GoalResponse'];
export type GoalUpdate = components['schemas']['GoalUpdate'];
export type PlanResponse = components['schemas']['PlanResponse'];
export type PlanAction = components['schemas']['PlanAction'];
export type PlanTask = components['schemas']['PlanTask'];
export type RevisionSummary = components['schemas']['RevisionSummary'];
export type PageSnapshot = components['schemas']['PageSnapshot'];
export type AnalyzePageRequest = components['schemas']['AnalyzePageRequest'];
export type AskRequest = components['schemas']['AskRequest'];
export type SessionResponse = components['schemas']['SessionResponse'];
export type SessionSummary = components['schemas']['SessionSummary'];
export type Guide = components['schemas']['Guide'];
export type ImportConversationRequest = components['schemas']['ImportConversationRequest'];
export type ConversationResponse = components['schemas']['ConversationResponse'];
export type ConversationSummary = components['schemas']['ConversationSummary'];
export type CandidateDecision = components['schemas']['CandidateDecision'];

export type GitHubStatus = components['schemas']['GitHubStatus'];
export type GitHubRepository = components['schemas']['GitHubRepository'];
export type AccountSession = components['schemas']['AccountSession'];
export type SettingsResponse = components['schemas']['SettingsResponse'];
export type AssessmentResponse = components['schemas']['AssessmentResponse'];
export type ArtifactResponse = components['schemas']['ArtifactResponse'];
export type PreviewRequest = components['schemas']['PreviewRequest'];

interface ClientOptions {
  baseUrl?: string;
  getToken?: () => string | undefined;
  onUnauthorized?: () => void;
}

export class ApiClient {
  private readonly baseUrl: string;
  private authEpoch = 0;
  constructor(private readonly options: ClientOptions = {}) {
    this.baseUrl = options.baseUrl ?? '/api/v1';
  }

  private async request<Output>(path: string, init: RequestInit = {}): Promise<Output> {
    const headers = new Headers(init.headers);
    if (init.body) headers.set('Content-Type', 'application/json');
    const token = this.options.getToken?.();
    const epoch = this.authEpoch;
    if (token) headers.set('Authorization', `Bearer ${token}`);
    const response = await fetch(`${this.baseUrl}${path}`, { ...init, headers, cache: 'no-store' });
    if (response.status === 401 && epoch === this.authEpoch && token === this.options.getToken?.()) this.options.onUnauthorized?.();
    if (!response.ok) {
      const body: unknown = await response.json().catch(() => null);
      const fallback = { code: 'SERVICE_UNAVAILABLE', message: '请求未完成，请稍后重试。', request_id: '' };
      if (body && typeof body === 'object' && 'code' in body && 'message' in body && 'request_id' in body &&
          typeof body.code === 'string' && typeof body.message === 'string' && typeof body.request_id === 'string') {
        throw new ApiError(response.status, { code: body.code, message: body.message, request_id: body.request_id });
      }
      throw new ApiError(response.status, fallback);
    }
    if (response.status === 204) return undefined as Output;
    return response.json() as Promise<Output>;
  }

  loginMock(identity: string, client: 'web' | 'extension' = 'web'): Promise<LoginResponse> {
    return this.request<LoginResponse>('/auth/mock-login', { method: 'POST', body: JSON.stringify({ identity, client }) }).then(value => { this.authEpoch++; return value; });
  }
  me(): Promise<UserResponse> { return this.request('/auth/me'); }
  authOptions(): Promise<AuthOptions> { return this.request('/auth/options'); }
  logout(): Promise<void> { return this.request('/auth/logout', { method: 'POST' }); }
  jobs(signal?: AbortSignal): Promise<JobResponse[]> {
    return this.request('/jobs', signal ? { signal } : {});
  }
  job(id: string): Promise<JobResponse> { return this.request(`/jobs/${encodeURIComponent(id)}`); }
  cancelJob(id: string): Promise<JobResponse> {
    return this.request(`/jobs/${encodeURIComponent(id)}/cancel`, { method: 'POST' });
  }
  retryJob(id: string): Promise<JobResponse> {
    return this.request(`/jobs/${encodeURIComponent(id)}/retry`, { method: 'POST' });
  }
  sources(signal?: AbortSignal): Promise<SourceResponse[]> {
    return this.request('/sources', signal ? { signal } : {});
  }
  connectSource(repository: string, folders = ''): Promise<SourceResponse> {
    return this.request('/sources', { method: 'POST', body: JSON.stringify({ external_ref: repository, consent: true, read_only: true, path_prefixes: folders.split(',').map(value => value.trim()).filter(Boolean) }) });
  }
  syncSource(id: string, key: string): Promise<JobResponse> {
    return this.request(`/sources/${encodeURIComponent(id)}/sync`, { method: 'POST', headers: { 'Idempotency-Key': key } });
  }
  updateSource(source: SourceResponse, status: 'CONNECTED' | 'PAUSED'): Promise<SourceResponse> {
    return this.request(`/sources/${encodeURIComponent(source.id)}`, { method: 'PATCH', body: JSON.stringify({ version: source.version, status }) });
  }
  updateSourceScope(source: SourceResponse, folders: string): Promise<SourceResponse> {
    return this.request(`/sources/${encodeURIComponent(source.id)}`, { method: 'PATCH', body: JSON.stringify({ version: source.version, status: 'CONNECTED', path_prefixes: folders.split(',').map(value => value.trim()).filter(Boolean) }) });
  }
  disconnectSource(id: string, deleteDerived: boolean): Promise<void> {
    return this.request(`/sources/${encodeURIComponent(id)}?delete_derived=${deleteDerived}`, { method: 'DELETE' });
  }
  documents(id: string, signal?: AbortSignal): Promise<DocumentResponse[]> {
    return this.request(`/sources/${encodeURIComponent(id)}/documents`, signal ? { signal } : {});
  }
  knowledge(q = '', offset = 0, signal?: AbortSignal): Promise<KnowledgeResponse[]> {
    return this.request(`/knowledge?q=${encodeURIComponent(q)}&offset=${offset}&limit=50`, signal ? { signal } : {});
  }
  evidence(id: string, signal?: AbortSignal): Promise<EvidenceResponse[]> {
    return this.request(`/knowledge/${encodeURIComponent(id)}/evidence`, signal ? { signal } : {});
  }
  correctKnowledge(id: string, correction: CorrectionRequest): Promise<KnowledgeResponse> {
    return this.request(`/knowledge/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify(correction) });
  }
  goals(signal?: AbortSignal): Promise<GoalResponse[]> {
    return this.request('/goals', signal ? { signal } : {});
  }
  createGoal(body: GoalInput, key: string): Promise<GoalResponse> {
    return this.request('/goals', { method: 'POST', headers: { 'Idempotency-Key': key }, body: JSON.stringify(body) });
  }
  updateGoal(id: string, body: GoalUpdate): Promise<GoalResponse> {
    return this.request(`/goals/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(body) });
  }
  deleteGoal(id: string): Promise<void> {
    return this.request(`/goals/${encodeURIComponent(id)}?confirm=true`, { method: 'DELETE' });
  }
  plans(goalId: string, signal?: AbortSignal): Promise<PlanResponse[]> {
    return this.request(`/plans?goal_id=${encodeURIComponent(goalId)}`, signal ? { signal } : {});
  }
  generatePlan(goal: GoalResponse, revision = 0): Promise<PlanResponse> {
    return this.request('/plans:generate', { method: 'POST', body: JSON.stringify({ goal_id: goal.id, goal_version: goal.version, expected_revision_no: revision }) });
  }
  planAction(id: string, body: PlanAction): Promise<PlanResponse> {
    return this.request(`/plans/${encodeURIComponent(id)}/actions`, { method: 'POST', body: JSON.stringify(body) });
  }
  planHistory(id: string, offset = 0): Promise<RevisionSummary[]> {
    return this.request(`/plans/${encodeURIComponent(id)}/revisions?offset=${offset}`);
  }
  planRevision(id: string, revision: number): Promise<PlanResponse> {
    return this.request(`/plans/${encodeURIComponent(id)}/revisions/${revision}`);
  }
  analyzePage(body: AnalyzePageRequest, key: string): Promise<SessionResponse> {
    return this.request('/pages:analyze', { method: 'POST', headers: { 'Idempotency-Key': key }, body: JSON.stringify(body) });
  }
  sessions(offset = 0): Promise<SessionSummary[]> { return this.request(`/sessions?offset=${offset}`); }
  session(id: string): Promise<SessionResponse> { return this.request(`/sessions/${encodeURIComponent(id)}`); }
  ask(id: string, body: AskRequest, key: string): Promise<SessionResponse> {
    return this.request(`/sessions/${encodeURIComponent(id)}/questions`, { method: 'POST', headers: { 'Idempotency-Key': key }, body: JSON.stringify(body) });
  }
  deleteSession(id: string): Promise<void> {
    return this.request(`/sessions/${encodeURIComponent(id)}?confirm=true`, { method: 'DELETE' });
  }
  importConversation(body: ImportConversationRequest, key: string): Promise<ConversationResponse> {
    return this.request('/conversations:import', { method: 'POST', headers: { 'Idempotency-Key': key }, body: JSON.stringify(body) });
  }
  conversations(offset = 0): Promise<ConversationSummary[]> { return this.request(`/conversations?offset=${offset}`); }
  conversation(id: string): Promise<ConversationResponse> { return this.request(`/conversations/${encodeURIComponent(id)}`); }
  decideConversation(id: string, candidate: string, body: CandidateDecision): Promise<ConversationResponse> {
    return this.request(`/conversations/${encodeURIComponent(id)}/candidates/${encodeURIComponent(candidate)}/decision`, { method: 'POST', body: JSON.stringify(body) });
  }
  deleteConversation(id: string): Promise<void> {
    return this.request(`/conversations/${encodeURIComponent(id)}?confirm=true`, { method: 'DELETE' });
  }
  assessments(): Promise<AssessmentResponse[]> { return this.request('/assessments'); }
  createAssessment(sessionId: string): Promise<AssessmentResponse> {
    return this.request('/assessments', { method: 'POST', body: JSON.stringify({ session_id: sessionId }) });
  }
  answerAssessment(item: AssessmentResponse, choice: 'A' | 'B' | 'C'): Promise<AssessmentResponse> {
    return this.request(`/assessments/${encodeURIComponent(item.id)}/answer`, { method: 'POST', body: JSON.stringify({ version: item.version, choice }) });
  }
  confirmAssessment(item: AssessmentResponse): Promise<AssessmentResponse> {
    return this.request(`/assessments/${encodeURIComponent(item.id)}/confirm`, { method: 'POST', body: JSON.stringify({ version: item.version, confirm: true }) });
  }
  artifacts(): Promise<ArtifactResponse[]> { return this.request('/artifacts'); }
  createArtifact(assessmentId: string): Promise<ArtifactResponse> {
    return this.request('/artifacts', { method: 'POST', body: JSON.stringify({ assessment_id: assessmentId }) });
  }
  editArtifact(item: ArtifactResponse, markdown: string): Promise<ArtifactResponse> {
    return this.request(`/artifacts/${encodeURIComponent(item.id)}`, { method: 'PUT', body: JSON.stringify({ version: item.version, markdown }) });
  }
  previewArtifact(id: string, body: PreviewRequest): Promise<ArtifactResponse> {
    return this.request(`/artifacts/${encodeURIComponent(id)}/preview`, { method: 'POST', body: JSON.stringify(body) });
  }
  reindexArtifact(item: ArtifactResponse): Promise<JobResponse> {
    return this.request(`/artifacts/${encodeURIComponent(item.id)}/reindex`, { method: 'POST', body: JSON.stringify({ version: item.version, confirm: true }) });
  }
  approveArtifact(item: ArtifactResponse, key: string): Promise<JobResponse> {
    return this.request(`/artifacts/${encodeURIComponent(item.id)}/approve`, { method: 'POST', headers: { 'Idempotency-Key': key }, body: JSON.stringify({ version: item.version, confirm: true }) });
  }

  settings(): Promise<SettingsResponse> { return this.request('/settings'); }
  updateSettings(item: SettingsResponse, allowed: boolean): Promise<SettingsResponse> {
    return this.request('/settings', { method: 'PUT', body: JSON.stringify({ version: item.version, cloud_processing_allowed: allowed, confirm: true }) });
  }
  exportData(): Promise<Record<string, unknown>> { return this.request('/settings/export'); }
  deleteData(): Promise<void> {
    return this.request('/settings/data', { method: 'DELETE', body: JSON.stringify({ confirmation: 'DELETE_MY_DATA' }) });
  }
  revokeWrite(sourceId: string): Promise<void> { return this.request(`/sources/${encodeURIComponent(sourceId)}/write-permission`, { method: 'DELETE' }); }

  accountLogin(identity: string, password: string, client: 'web' | 'extension', register = false): Promise<AccountSession> {
    return this.request<AccountSession>(register ? '/auth/register' : '/auth/login', { method: 'POST', body: JSON.stringify({ identity, password, client }) }).then(value => { this.authEpoch++; return value; });
  }
  recoverAccount(identity: string, password: string, recovery_code: string, client: 'web' | 'extension'): Promise<{ recovery_code: string }> {
    return this.request('/auth/recover', { method: 'POST', body: JSON.stringify({ identity, password, recovery_code, client }) });
  }

  githubStatus(): Promise<GitHubStatus> { return this.request('/github/status'); }
  githubAuthorize(): Promise<{ authorization_url: string }> { return this.request('/github/authorize', { method: 'POST' }); }
  githubInstallations(page = 1): Promise<components['schemas']['InstallationList']> { return this.request(`/github/installations?page=${page}`); }
  githubRepositories(installation: number, page = 1): Promise<components['schemas']['RepositoryList']> { return this.request(`/github/installations/${installation}/repositories?page=${page}`); }
  githubConnectRepository(installation: number, repo: GitHubRepository, folders: string): Promise<SourceResponse> {
    return this.request('/github/sources', { method: 'POST', body: JSON.stringify({ installation_id: installation, repository_id: repo.id, repository: repo.full_name, path_prefixes: folders.split(',').map(value => value.trim()).filter(Boolean), confirm: true }) });
  }
  githubGrantWrite(source: SourceResponse, folders: string): Promise<void> {
    return this.request(`/github/sources/${encodeURIComponent(source.id)}/write-permission`, { method: 'PUT', body: JSON.stringify({ version: source.version, path_prefixes: folders.split(',').map(value => value.trim()).filter(Boolean), confirm: true }) });
  }
  githubDisconnect(): Promise<void> { return this.request('/github/connection', { method: 'DELETE' }); }

}
