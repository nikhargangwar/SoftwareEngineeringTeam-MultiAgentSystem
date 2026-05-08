import { Component } from '@angular/core';

import { RunSummary, Stage } from './models';
import { SweTeamApiService } from './swe-team-api.service';

const DEFAULT_STAGES: Stage[] = [
  { step: 1, name: 'Issue Reader Agent', description: 'Fetches the GitHub issue, labels, and comments.' },
  { step: 2, name: 'Issue Analyzer Agent', description: 'Understands the task, severity, keywords, and approach.' },
  { step: 3, name: 'Repo Explorer Agent', description: 'Reads the repository tree and filters code files.' },
  { step: 4, name: 'File Locator Agent', description: 'Ranks the files most likely to need changes.' },
  { step: 5, name: 'Code Reader Agent', description: 'Loads source content for selected files.' },
  { step: 6, name: 'Solution Designer Agent', description: 'Designs the implementation plan before code is written.' },
  { step: 7, name: 'Code Writer Agent', description: 'Generates complete updated file contents.' },
  { step: 8, name: 'Code Reviewer Agent', description: 'Reviews generated changes and keeps approved files.' },
  { step: 9, name: 'Test Writer Agent', description: 'Creates or updates tests for the fix.' },
  { step: 10, name: 'Git Commit Agent', description: 'Creates a branch and commits approved changes.' },
  { step: 11, name: 'PR Creator Agent', description: 'Opens a pull request and links the issue.' }
];

@Component({
  selector: 'app-root',
  templateUrl: './app.component.html',
  styleUrls: ['./app.component.css']
})
export class AppComponent {
  repo = '';
  issueId: number | null = null;
  runId = '';
  runStatus: 'idle' | 'queued' | 'running' | 'completed' | 'failed' = 'idle';
  stages: Stage[] = DEFAULT_STAGES.map(stage => ({ ...stage, status: 'pending' }));
  logs: string[] = [];
  result: RunSummary | null = null;
  errorMessage = '';

  constructor(private api: SweTeamApiService) {}

  get completedCount(): number {
    return this.stages.filter(stage => stage.status === 'completed').length;
  }

  get progressPercent(): number {
    return Math.round((this.completedCount / this.stages.length) * 100);
  }

  get currentStage(): Stage | undefined {
    return this.stages.find(stage => stage.status === 'running');
  }

  start(): void {
    if (!this.repo.trim() || !this.issueId) {
      this.errorMessage = 'Enter a GitHub repo and issue ID to start the team.';
      return;
    }

    this.resetRun();
    this.runStatus = 'queued';

    this.api.startRun(this.repo.trim(), this.issueId).subscribe({
      next: response => {
        this.runId = response.run_id;
        this.listen(response.run_id);
      },
      error: () => {
        this.runStatus = 'failed';
        this.errorMessage = 'Could not start the backend run. Check that FastAPI is running.';
      }
    });
  }

  private listen(runId: string): void {
    this.api.streamRun(runId).subscribe({
      next: event => this.handleEvent(event.type, event.data),
      error: () => {
        if (this.runStatus !== 'completed' && this.runStatus !== 'failed') {
          this.runStatus = 'failed';
          this.errorMessage = 'The live progress stream disconnected.';
        }
      }
    });
  }

  private handleEvent(type: string, data: any): void {
    if (type === 'started') {
      this.runStatus = 'running';
      if (Array.isArray(data.stages)) {
        this.stages = data.stages.map((stage: Stage) => ({ ...stage, status: 'pending' }));
      }
      this.logs.unshift(`Run started for ${data.repo} issue #${data.issue_id}`);
    }

    if (type === 'stage') {
      this.markStageRunning(data.step);
    }

    if (type === 'log' && data.line) {
      this.logs.unshift(data.line);
      this.logs = this.logs.slice(0, 90);
    }

    if (type === 'completed') {
      this.finishOpenStage('completed');
      this.runStatus = data.success ? 'completed' : 'failed';
      this.result = data;
    }

    if (type === 'failed') {
      this.finishOpenStage('failed');
      this.runStatus = 'failed';
      this.result = data;
      this.errorMessage = data?.errors?.fatal || 'The SWE team run failed.';
    }
  }

  private markStageRunning(step: number): void {
    this.stages = this.stages.map(stage => {
      if (stage.step < step && stage.status !== 'completed') {
        return { ...stage, status: 'completed', completedAt: new Date() };
      }
      if (stage.step === step) {
        return { ...stage, status: 'running', startedAt: stage.startedAt || new Date() };
      }
      return stage;
    });
  }

  private finishOpenStage(status: 'completed' | 'failed'): void {
    this.stages = this.stages.map(stage => {
      if (stage.status === 'running') {
        return { ...stage, status, completedAt: new Date() };
      }
      if (status === 'completed' && stage.status === 'pending') {
        return { ...stage, status: 'completed', completedAt: new Date() };
      }
      return stage;
    });
  }

  private resetRun(): void {
    this.runId = '';
    this.result = null;
    this.errorMessage = '';
    this.logs = [];
    this.stages = DEFAULT_STAGES.map(stage => ({ ...stage, status: 'pending' }));
  }
}
