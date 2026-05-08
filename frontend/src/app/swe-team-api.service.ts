import { Injectable, NgZone } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../environments/environment';
import { RunCreated } from './models';

export interface StreamEvent {
  type: string;
  data: any;
}

@Injectable({
  providedIn: 'root'
})
export class SweTeamApiService {
  private readonly apiBase = environment.apiBaseUrl;

  constructor(private http: HttpClient, private zone: NgZone) {}

  startRun(repo: string, issueId: number): Observable<RunCreated> {
    return this.http.post<RunCreated>(`${this.apiBase}/api/runs`, {
      repo,
      issue_id: issueId
    });
  }

  streamRun(runId: string): Observable<StreamEvent> {
    return new Observable<StreamEvent>(observer => {
      const source = new EventSource(`${this.apiBase}/api/runs/${runId}/events`);
      const eventNames = ['connected', 'started', 'stage', 'log', 'completed', 'failed', 'close', 'heartbeat'];

      const emit = (type: string) => (event: MessageEvent) => {
        this.zone.run(() => {
          observer.next({
            type,
            data: event.data ? JSON.parse(event.data) : {}
          });
        });
      };

      eventNames.forEach(name => source.addEventListener(name, emit(name)));
      source.onerror = error => {
        this.zone.run(() => observer.error(error));
        source.close();
      };

      return () => source.close();
    });
  }
}
