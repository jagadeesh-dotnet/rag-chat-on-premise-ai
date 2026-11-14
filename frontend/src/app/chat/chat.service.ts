import { Injectable, NgZone } from '@angular/core';
import { Router } from '@angular/router';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { AuthService } from '../auth/auth.service';
import { ChatEvent, ChatMessage } from './chat.models';

@Injectable({ providedIn: 'root' })
export class ChatService {
  private readonly url = `${environment.apiUrl}/api/chat`;

  constructor(
    private auth: AuthService,
    private router: Router,
    private zone: NgZone,
  ) {}

  /** Streams the answer as events. Unsubscribing cancels the request. */
  streamChat(messages: ChatMessage[]): Observable<ChatEvent> {
    return new Observable<ChatEvent>((subscriber) => {
      const controller = new AbortController();

      const run = async () => {
        const response = await fetch(this.url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ messages }),
          signal: controller.signal,
          credentials: 'include', // send the session cookie (fetch doesn't go through the HTTP interceptor)
        });

        if (response.status === 401) {
          this.zone.run(() => {
            this.auth.signedOut();
            this.router.navigate(['/login'], { queryParams: { returnUrl: this.router.url } });
          });
          throw new Error('Your session has ended. Please sign in again.');
        }
        if (response.status === 403) {
          this.zone.run(() => this.router.navigate(['/change-password']));
          throw new Error('Please change your temporary password first.');
        }
        if (!response.ok || !response.body) {
          throw new Error(`Server returned ${response.status}: ${await response.text()}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { value, done } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() ?? ''; // the last piece may be an unfinished line

          for (const line of lines) {
            if (line.trim()) {
              subscriber.next(JSON.parse(line) as ChatEvent);
            }
          }
        }

        if (buffer.trim()) {
          subscriber.next(JSON.parse(buffer) as ChatEvent); // a final line without "\n"
        }
        subscriber.complete();
      };

      run().catch((err: unknown) => {
        if (controller.signal.aborted) return; // we cancelled it: not an error
        subscriber.error(err);
      });

      return () => controller.abort(); // teardown: runs on unsubscribe
    });
  }
}