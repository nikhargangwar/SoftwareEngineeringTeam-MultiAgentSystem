export interface Stage {
  step: number;
  name: string;
  description: string;
  status?: 'pending' | 'running' | 'completed' | 'failed';
  startedAt?: Date;
  completedAt?: Date;
}

export interface RunSummary {
  success: boolean;
  elapsed_seconds?: number;
  pr?: {
    pr_number?: number;
    pr_url?: string;
    pr_title?: string;
    branch?: string;
  };
  analysis?: {
    issue_type?: string;
    severity?: string;
    complexity?: string;
    summary?: string;
    approach?: string;
  };
  files_changed?: string[];
  errors?: Record<string, string>;
}

export interface RunCreated {
  run_id: string;
  status: string;
}
