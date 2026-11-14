import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { BehaviorSubject, Observable, tap } from 'rxjs';

import { environment } from '../../environments/environment';
import { Conversation, ConversationSummary, UiMessage } from './chat.models';

/** Saved conversations (backend: data/chat.db). The sidebar watches `list$`. */
@Injectable({ providedIn: 'root' })
export class ConversationService {
  private readonly url = `${environment.apiUrl}/api/conversations`;
  readonly list$ = new BehaviorSubject<ConversationSummary[]>([]);

  constructor(private http: HttpClient) {}

  refresh(): void {
    this.http.get<ConversationSummary[]>(this.url).subscribe({
      next: (list) => this.list$.next(list),
      error: () => this.list$.next([]), // backend down: empty sidebar, chat still usable
    });
  }

  get(id: string): Observable<Conversation> {
    return this.http.get<Conversation>(`${this.url}/${id}`);
  }

  save(id: string, messages: UiMessage[]): Observable<unknown> {
    return this.http.put(`${this.url}/${id}`, { messages }).pipe(tap(() => this.refresh()));
  }

  rename(id: string, title: string): Observable<unknown> {
    return this.http.patch(`${this.url}/${id}`, { title }).pipe(tap(() => this.refresh()));
  }

  delete(id: string): Observable<unknown> {
    return this.http.delete(`${this.url}/${id}`).pipe(tap(() => this.refresh()));
  }
}
