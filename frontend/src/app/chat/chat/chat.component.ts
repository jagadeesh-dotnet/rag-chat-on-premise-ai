import { Location } from '@angular/common';
import { AfterViewChecked, Component, ElementRef, OnDestroy, OnInit, ViewChild } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { Subscription } from 'rxjs';

import { ChatService } from '../chat.service';
import { ChatEvent, ChatMessage, UiMessage } from '../chat.models';
import { ConversationService } from '../conversation.service';

const STEP_LABELS: Record<string, [string, string, string]> = {
  // tool: [while running, when done, what it counts]
  search_documents: ['Searching', 'Searched', 'passages'],
  query_tables: ['Querying spreadsheets', 'Queried spreadsheets', 'rows'],
  get_schema: ['Reading tables of', 'Read tables of', 'tables'],
  run_sql: ['Querying', 'Queried', 'rows'],
};

const EXAMPLES = [
  'How many days of annual leave do employees get?',
  'What does clause 6.2 of ISO 27001 require?',
  'Show total sales and profit per category in the spreadsheet',
  'Who were the top 5 Northwind customers by revenue in 1997?',
];

@Component({
  selector: 'app-chat',
  templateUrl: './chat.component.html',
  styleUrls: ['./chat.component.scss'],
})
export class ChatComponent implements OnInit, AfterViewChecked, OnDestroy {
  @ViewChild('scroller') private scroller?: ElementRef<HTMLElement>;

  readonly examples = EXAMPLES;
  messages: UiMessage[] = [];
  input = '';
  streaming = false;
  conversationId: string | null = null;
  sidebarOpen = false;
  highlighted: string | null = null; // "messageIndex-sourceNumber" of the citation just clicked

  private subscription?: Subscription;
  private routeSubscription?: Subscription;
  private scrollPending = false;

  constructor(
    private chat: ChatService,
    private conversations: ConversationService,
    private route: ActivatedRoute,
    private router: Router,
    private location: Location,
  ) {}

  ngOnInit(): void {
    this.routeSubscription = this.route.paramMap.subscribe((params) => this.openConversation(params.get('id')));
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
    this.routeSubscription?.unsubscribe();
  }

  get title(): string {
    const saved = this.conversations.list$.value.find((c) => c.id === this.conversationId);
    return saved?.title ?? this.messages.find((m) => m.role === 'user')?.content ?? 'New chat';
  }

  // --- conversations ----------------------------------------------------------------------------------

  newChat(): void {
    this.stop();
    this.conversationId = null;
    this.messages = [];
    this.sidebarOpen = false;
    this.location.replaceState('/');
    this.router.navigateByUrl('/');
  }

  private openConversation(id: string | null): void {
    if (id === this.conversationId) return; // e.g. our own URL update after the first question
    this.subscription?.unsubscribe();
    this.streaming = false;
    this.conversationId = id;
    this.messages = [];
    if (!id) return;
    this.conversations.get(id).subscribe({
      next: (conversation) => {
        if (this.conversationId !== id) return; // user already moved on
        this.messages = conversation.messages;
        this.scrollPending = true;
      },
      error: () => this.newChat(), // deleted or unknown id
    });
  }

  private persist(): void {
    const id = this.conversationId;
    const messages = this.messages.filter((m) => m.content || m.tables?.length);
    if (id && messages.some((m) => m.role === 'assistant')) {
      this.conversations.save(id, messages).subscribe({ error: () => undefined }); // saving is best effort
    }
  }

  // --- asking -----------------------------------------------------------------------------------------

  send(text = this.input): void {
    text = text.trim();
    if (!text || this.streaming) return;
    if (!this.conversationId) {
      this.conversationId = crypto.randomUUID();
      // Change the URL without a router navigation, which would recreate this component mid-answer.
      this.location.replaceState(`/c/${this.conversationId}`);
    }
    this.messages.push({ role: 'user', content: text });
    this.input = '';
    this.answer();
  }

  regenerate(): void {
    if (this.streaming) return;
    if (this.messages[this.messages.length - 1]?.role === 'assistant') this.messages.pop();
    this.answer();
  }

  stop(): void {
    if (!this.streaming) return;
    this.subscription?.unsubscribe(); // teardown aborts the fetch, and the server stops the model
    this.streaming = false;
    const last = this.messages[this.messages.length - 1];
    if (last?.role === 'assistant' && !last.content && !last.tables?.length) this.messages.pop(); // empty bubble
    this.persist();
  }

  onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault(); // Enter sends; Shift+Enter keeps the new line
      this.send();
    }
  }

  private answer(): void {
    const history = this.history();
    const answer: UiMessage = { role: 'assistant', content: '' };
    this.messages.push(answer);
    this.streaming = true;
    this.scrollPending = true;

    this.subscription = this.chat.streamChat(history).subscribe({
      next: (event) => this.apply(event, answer),
      error: (err: unknown) => {
        this.fail(answer, err instanceof Error ? err.message : String(err));
        this.streaming = false;
        this.persist();
      },
      complete: () => {
        this.streaming = false;
        this.persist(); // once per answer, not on every token
      },
    });
  }

  /** What the model sees: text only, and questions whose answer failed are left out with it. */
  private history(): ChatMessage[] {
    const result: ChatMessage[] = [];
    this.messages.forEach((m, i) => {
      if (m.role === 'user') {
        const reply = this.messages[i + 1];
        const isLast = i === this.messages.length - 1;
        if (isLast || (reply?.role === 'assistant' && !reply.error && reply.content)) {
          result.push({ role: 'user', content: m.content });
        }
      } else if (!m.error && m.content) {
        result.push({ role: 'assistant', content: m.content });
      }
    });
    return result;
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
      case 'table': {
        const { type: _type, ...table } = event;
        answer.tables = [...(answer.tables ?? []), table];
        this.scrollPending = true;
        break;
      }
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

  private fail(answer: UiMessage, message: string): void {
    answer.error = true;
    answer.content = answer.content ? `${answer.content}\n\n⚠ ${message}` : `⚠ ${message}`;
  }

  // --- display ----------------------------------------------------------------------------------------

  workSummary(m: UiMessage, isLast: boolean): string {
    const steps = m.steps ?? [];
    if (this.streaming && isLast) return steps[steps.length - 1];
    return `Used ${steps.length} tool${steps.length === 1 ? '' : 's'}`;
  }

  /** Click on [n] in an answer: scroll to source n of that answer and highlight it. */
  onAnswerClick(event: MouseEvent, index: number): void {
    const cite = (event.target as HTMLElement).closest('a.cite');
    if (!cite) return;
    event.preventDefault();
    const key = `${index}-${cite.getAttribute('data-n')}`;
    document.getElementById(`src-${key}`)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    this.highlighted = key;
    setTimeout(() => {
      if (this.highlighted === key) this.highlighted = null;
    }, 2000);
  }
}
