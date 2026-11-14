import { AfterViewChecked, Component, ElementRef, OnDestroy, ViewChild } from '@angular/core';
import { Subscription } from 'rxjs';
import { ChatService } from '../chat.service';
import { ChatEvent, ChatMessage, Source, TableResult } from '../chat.models';


/** A message as shown on screen: the API fields plus display-only state. */
interface UiMessage extends ChatMessage {
  thinking?: string;
  error?: boolean;
  steps?: string[]; // e.g. 'Searched: "clause 6.2" (5 passages)'
  sources?: Source[];
  tables?: TableResult[];
}

const STEP_LABELS: Record<string, [string, string, string]> = {
  // tool: [while running, when done, what it counts]
  search_documents: ['Searching', 'Searched', 'passages'],
  query_tables: ['Querying spreadsheets', 'Queried spreadsheets', 'rows'],
  get_schema: ['Reading tables of', 'Read tables of', 'tables'],
  run_sql: ['Querying', 'Queried', 'rows'],
};

@Component({
  selector: 'app-chat',
  templateUrl: './chat.component.html',
  styleUrls: ['./chat.component.scss'],
})
export class ChatComponent implements AfterViewChecked, OnDestroy {
  @ViewChild('scroller') private scroller?: ElementRef<HTMLElement>;

  messages: UiMessage[] = [];
  input = '';
  streaming = false;

  private subscription?: Subscription;
  private scrollPending = false;

  constructor(private chat: ChatService) {}

  send(): void {
    const text = this.input.trim();
    if (!text || this.streaming) return;

    // History for the server: real turns only (no errors, no empty placeholders), ending with the new question.
    const history: ChatMessage[] = this.messages
      .filter((m) => !m.error && m.content)
      .map(({ role, content }) => ({ role, content }));
    history.push({ role: 'user', content: text });

    this.messages.push({ role: 'user', content: text });
    const answer: UiMessage = { role: 'assistant', content: '' };
    this.messages.push(answer);
    this.input = '';
    this.streaming = true;
    this.scrollPending = true;

    this.subscription = this.chat.streamChat(history).subscribe({
      next: (event) => this.apply(event, answer),
      error: (err: unknown) => {
        this.fail(answer, err instanceof Error ? err.message : String(err));
        this.streaming = false;
      },
      complete: () => (this.streaming = false),
    });
  }

  stop(): void {
    this.subscription?.unsubscribe(); // teardown aborts the fetch, and the server stops the model
    this.streaming = false;
  }

  onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault(); // Enter sends; Shift+Enter keeps the new line
      this.send();
    }
  }

  ngAfterViewChecked(): void {
    if (this.scrollPending && this.scroller) {
      const el = this.scroller.nativeElement;
      el.scrollTop = el.scrollHeight;
      this.scrollPending = false;
    }
  }

  ngOnDestroy(): void {
    this.subscription?.unsubscribe();
  }

  private apply(event: ChatEvent, answer: UiMessage): void {
    switch (event.type) {
      case 'thinking':
        answer.thinking = (answer.thinking ?? '') + event.content;
        break;
      case 'token':
        answer.content += event.content;
        this.scrollPending = true;
        break;
      case 'tool_call': {
        const [running] = STEP_LABELS[event.name] ?? ['Running ' + event.name];
        const { query, database } = event.arguments;
        const detail = query ? `: "${query}"` : database ? ` ${database}` : '';
        answer.steps = [...(answer.steps ?? []), running + detail];
        this.scrollPending = true;
        break;
      }
      case 'tool_result': {
        const [running, done, unit] = STEP_LABELS[event.name] ?? ['Running', 'Ran', 'results'];
        const outcome = !event.ok ? 'error, retrying' : event.count ? `${event.count} ${unit}` : 'nothing found';
        const steps = answer.steps ?? [];
        steps[steps.length - 1] = steps[steps.length - 1].replace(running, done) + ` (${outcome})`;
        break;
      }
      case 'table':
        answer.tables = [...(answer.tables ?? []), event];
        this.scrollPending = true;
        break;
      case 'sources':
        answer.sources = event.items;
        this.scrollPending = true;
        break;
      case 'error':
        this.fail(answer, event.message);
        break;
      case 'done':
        break;
    }
  }

  isNumber(value: unknown): boolean {
    return typeof value === 'number'; // `typeof` isn't allowed in Angular 16 templates
  }

  /** 1565804.3232 -> "1,565,804.32"; text stays as it is. */
  formatCell(value: string | number | null): string {
    if (value === null) return '';
    return typeof value === 'number' ? value.toLocaleString(undefined, { maximumFractionDigits: 2 }) : value;
  }

  private fail(answer: UiMessage, message: string): void {
    answer.error = true;
    answer.content = answer.content ? `${answer.content}\n\n⚠ ${message}` : `⚠ ${message}`;
  }
}