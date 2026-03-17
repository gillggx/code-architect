/**
 * API Client for Code Architect Backend
 * 
 * Provides typed HTTP client for all API endpoints with
 * automatic error handling and WebSocket management.
 * 
 * Version: 1.0
 */

import axios, { AxiosInstance, AxiosError } from 'axios';

/**
 * HTTP client configuration
 * 
 * Properties:
 *   - baseURL: Backend API URL
 *   - timeout: Request timeout in ms
 *   - headers: Default headers
 */
interface ClientConfig {
  baseURL: string;
  timeout: number;
  apiKey?: string;
}

/**
 * Analysis request parameters
 */
export interface AnalysisRequest {
  project_path: string;
  project_id?: string;
  languages?: string[];
  include_patterns?: boolean;
  include_search?: boolean;
  sample_ratio?: number;
}

/**
 * Analysis result with detected patterns
 */
export interface AnalysisResult {
  job_id: string;
  project_id: string;
  project_path: string;
  status: string;
  patterns_detected: PatternMatch[];
  total_files: number;
  supported_languages: string[];
  analysis_time_seconds: number;
  timestamp: string;
}

/**
 * Detected architectural pattern
 */
export interface PatternMatch {
  name: string;
  category: string;
  confidence: number;
  evidence_count: number;
  locations: Array<{
    file: string;
    start_line: number;
    end_line: number;
  }>;
}

/**
 * Analysis progress update
 */
export interface AnalysisProgress {
  job_id: string;
  status: string;
  progress_percent: number;
  files_processed: number;
  files_total: number;
  current_step: string;
  eta_seconds?: number;
}

/**
 * Search request parameters
 */
export interface SearchRequest {
  query: string;
  project_id?: string;
  top_k?: number;
  include_patterns?: boolean;
  confidence_threshold?: number;
}

/**
 * Search result item
 */
export interface SearchResultItem {
  id: string;
  type: string;
  title: string;
  content: string;
  confidence: number;
  location?: {
    file: string;
    line: number;
  };
  source: string;
}

/**
 * Search response
 */
export interface SearchResponse {
  query: string;
  results: SearchResultItem[];
  total_results: number;
  execution_time_ms: number;
}

/**
 * Project information
 */
export interface ProjectInfo {
  project_id: string;
  project_path: string;
  created_at: string;
  last_analyzed?: string;
  languages: string[];
  file_count: number;
  pattern_count: number;
}

/**
 * Health status
 */
export interface HealthStatus {
  status: string;
  version: string;
  uptime_seconds: number;
  timestamp: string;
}

/**
 * Validation request
 */
export interface ValidationRequest {
  code: string;
  language: string;
  validate_syntax?: boolean;
  validate_patterns?: boolean;
}

/**
 * Validation issue
 */
export interface ValidationIssue {
  type: string;
  message: string;
  line: number;
  column: number;
  severity: string;
}

/**
 * Validation response
 */
export interface ValidationResponse {
  valid: boolean;
  issues: ValidationIssue[];
  suggestions: string[];
}

/**
 * API Client class
 * 
 * Manages all HTTP communication with the backend API.
 * Provides typed methods for each endpoint with automatic
 * error handling and request/response transformation.
 */
export class APIClient {
  private client: AxiosInstance;
  private config: ClientConfig;

  /**
   * Initialize API client
   * 
   * Args:
   *   config: Client configuration
   */
  constructor(config: Partial<ClientConfig> = {}) {
    this.config = {
      baseURL: config.baseURL || 'http://localhost:8000',
      timeout: config.timeout || 30000,
      apiKey: config.apiKey,
    };

    this.client = axios.create({
      baseURL: this.config.baseURL,
      timeout: this.config.timeout,
    });

    // Add API key header if provided
    if (this.config.apiKey) {
      this.client.defaults.headers.common['X-API-Key'] = this.config.apiKey;
    }

    // Add error handler
    this.client.interceptors.response.use(
      (response) => response,
      (error) => this.handleError(error)
    );
  }

  /**
   * Handle API errors
   * 
   * Args:
   *   error: Axios error
   * 
   * Returns:
   *   Promise rejection with error details
   */
  private handleError(error: AxiosError): Promise<never> {
    const message = error.response?.data?.detail || error.message;
    const errorCode = error.response?.data?.error_code || 'UNKNOWN_ERROR';

    console.error(`API Error [${errorCode}]: ${message}`);
    return Promise.reject({
      code: errorCode,
      message,
      status: error.response?.status,
    });
  }

  /**
   * Get API health status
   * 
   * Returns:
   *   Promise resolving to HealthStatus
   */
  async getHealth(): Promise<HealthStatus> {
    const response = await this.client.get<HealthStatus>('/health');
    return response.data;
  }

  /**
   * Analyze a project
   * 
   * Args:
   *   request: Analysis request parameters
   * 
   * Returns:
   *   Promise resolving to AnalysisResult
   */
  async analyzeProject(request: AnalysisRequest): Promise<AnalysisResult> {
    const response = await this.client.post<AnalysisResult>(
      '/api/analyze',
      request
    );
    return response.data;
  }

  /**
   * Get analysis job progress
   * 
   * Args:
   *   jobId: Analysis job ID
   * 
   * Returns:
   *   Promise resolving to AnalysisProgress
   */
  async getJobProgress(jobId: string): Promise<AnalysisProgress> {
    const response = await this.client.get<AnalysisProgress>(
      `/api/jobs/${jobId}`
    );
    return response.data;
  }

  /**
   * Search project semantically
   * 
   * Args:
   *   request: Search request parameters
   * 
   * Returns:
   *   Promise resolving to SearchResponse
   */
  async search(request: SearchRequest): Promise<SearchResponse> {
    const response = await this.client.post<SearchResponse>(
      '/api/search',
      request
    );
    return response.data;
  }

  /**
   * List all projects
   * 
   * Returns:
   *   Promise resolving to list of ProjectInfo
   */
  async listProjects(): Promise<ProjectInfo[]> {
    const response = await this.client.get<{ projects: ProjectInfo[] }>(
      '/api/projects'
    );
    return response.data.projects;
  }

  /**
   * Validate code snippet
   * 
   * Args:
   *   request: Validation request
   * 
   * Returns:
   *   Promise resolving to ValidationResponse
   */
  async validateCode(request: ValidationRequest): Promise<ValidationResponse> {
    const response = await this.client.post<ValidationResponse>(
      '/api/validate',
      request
    );
    return response.data;
  }

  /**
   * Get pattern suggestions for code
   * 
   * Args:
   *   codeSnippet: Code to analyze
   *   language: Programming language
   * 
   * Returns:
   *   Promise resolving to suggestions
   */
  async suggestPatterns(
    codeSnippet: string,
    language: string
  ): Promise<any> {
    const response = await this.client.post(
      '/api/suggest',
      {
        code_snippet: codeSnippet,
        language,
      }
    );
    return response.data;
  }

  /**
   * Create WebSocket connection for real-time updates
   * 
   * Args:
   *   jobId: Analysis job ID
   *   handlers: Callback handlers for messages
   * 
   * Returns:
   *   WebSocket instance
   */
  connectWebSocket(
    jobId: string,
    handlers: {
      onProgress?: (progress: AnalysisProgress) => void;
      onComplete?: (result: any) => void;
      onError?: (error: string) => void;
      onClose?: () => void;
    }
  ): WebSocket {
    const protocol = this.config.baseURL.startsWith('https') ? 'wss' : 'ws';
    const host = new URL(this.config.baseURL).host;
    const wsUrl = `${protocol}://${host}/ws/analyze/${jobId}`;

    const ws = new WebSocket(wsUrl);

    ws.onmessage = (event) => {
      const message = JSON.parse(event.data);
      
      if (message.type === 'progress' && handlers.onProgress) {
        handlers.onProgress(message.data);
      } else if (message.type === 'complete' && handlers.onComplete) {
        handlers.onComplete(message.data);
      } else if (message.type === 'error' && handlers.onError) {
        handlers.onError(message.data.error);
      }
    };

    ws.onclose = () => {
      if (handlers.onClose) {
        handlers.onClose();
      }
    };

    return ws;
  }
}

// Create global API client instance
export const apiClient = new APIClient();

export default apiClient;
