import { Component, EventEmitter, Input, OnInit, Output } from '@angular/core';
import { Router } from '@angular/router';
import { map } from 'rxjs';

import { ConversationSummary } from '../chat.models';
import { ConversationService } from '../conversation.service';

interface Group {
  label: string;
  items: ConversationSummary[];
}

/** New chat button + saved conversations (Today / Previous 7 days / Older), with rename and delete. */
@Component({
  selector: 'app-sidebar',
  templateUrl: './sidebar.component.html',
  styleUrls: ['./sidebar.component.scss'],
})
export class SidebarComponent implements OnInit {
  @Input() activeId: string | null = null;
  @Output() newChat = new EventEmitter<void>();
  @Output() picked = new EventEmitter<void>(); // a conversation was chosen (closes the sidebar on mobile)

  menuFor: string | null = null;
  editingId: string | null = null;
  editTitle = '';

  readonly groups$ = this.conversations.list$.pipe(map(groupByAge));

  constructor(
    private conversations: ConversationService,
    private router: Router,
  ) {}

  ngOnInit(): void {
    this.conversations.refresh();
  }

  open(id: string): void {
    this.menuFor = null;
    this.router.navigate(['/c', id]);
    this.picked.emit();
  }

  toggleMenu(id: string, event: Event): void {
    event.stopPropagation();
    this.menuFor = this.menuFor === id ? null : id;
  }

  startRename(item: ConversationSummary, event: Event): void {
    event.stopPropagation();
    this.menuFor = null;
    this.editingId = item.id;
    this.editTitle = item.title;
  }

  saveRename(): void {
    const id = this.editingId;
    const title = this.editTitle.trim();
    this.editingId = null;
    if (id && title) this.conversations.rename(id, title).subscribe();
  }

  remove(item: ConversationSummary, event: Event): void {
    event.stopPropagation();
    this.menuFor = null;
    if (!confirm(`Delete "${item.title}"?`)) return;
    this.conversations.delete(item.id).subscribe(() => {
      if (item.id === this.activeId) this.newChat.emit(); // deleted the open chat: start a new one
    });
  }

  trackById(_: number, item: ConversationSummary): string {
    return item.id;
  }
}

function groupByAge(list: ConversationSummary[]): Group[] {
  const startOfToday = new Date();
  startOfToday.setHours(0, 0, 0, 0);
  const weekAgo = startOfToday.getTime() - 6 * 24 * 3600 * 1000;
  const groups: Group[] = [
    { label: 'Today', items: [] },
    { label: 'Previous 7 days', items: [] },
    { label: 'Older', items: [] },
  ];
  for (const item of list) {
    const time = new Date(item.updated).getTime();
    groups[time >= startOfToday.getTime() ? 0 : time >= weekAgo ? 1 : 2].items.push(item);
  }
  return groups.filter((g) => g.items.length);
}
