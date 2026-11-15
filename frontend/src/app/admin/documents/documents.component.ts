import { Component, OnInit } from '@angular/core';

import { AdminService, DocumentFile, IndexSummary, errorText } from '../admin.service';

type Status = DocumentFile['status'];

const STATUS_TEXT: Record<Status, string> = {
  indexed: 'Indexed',
  changed: 'Changed – re-index',
  new: 'New – not indexed yet',
  missing: 'File removed – drops out on re-index',
};

/**
 * Document files in data/docs compared with the search index, and buttons to index them.
 * Spreadsheets and databases are not here: they are read directly and need no indexing.
 */
@Component({
  selector: 'app-admin-documents',
  templateUrl: './documents.component.html',
  styleUrls: ['../admin.scss'],
})
export class DocumentsComponent implements OnInit {
  files: DocumentFile[] = [];
  folder = '';
  loading = true;
  running: 'changed' | 'all' | null = null;
  result?: IndexSummary;
  resultWasFull = false;
  error = '';

  constructor(private admin: AdminService) {}

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.loading = true;
    this.admin.documents().subscribe({
      next: (status) => {
        this.files = status.files;
        this.folder = status.folder;
        this.loading = false;
      },
      error: (err) => {
        this.error = errorText(err);
        this.loading = false;
      },
    });
  }

  /** Files the next normal run will touch: new, changed or removed. */
  get pending(): number {
    return this.files.filter((f) => f.status !== 'indexed').length;
  }

  count(status: Status): number {
    return this.files.filter((f) => f.status === status).length;
  }

  statusText(status: Status): string {
    return STATUS_TEXT[status];
  }

  get errorList(): [string, string][] {
    return Object.entries(this.result?.errors ?? {});
  }

  reindex(force: boolean): void {
    if (
      force &&
      !confirm('Re-index every document from scratch? Every chunk is embedded again, which takes longer than a normal run.')
    ) {
      return;
    }
    this.error = '';
    this.result = undefined;
    this.running = force ? 'all' : 'changed';
    this.admin.reindex(force).subscribe({
      next: (summary) => {
        this.result = summary;
        this.resultWasFull = force;
        this.running = null;
        this.load();
      },
      error: (err) => {
        this.error = err.status === 409 ? 'Indexing is already running. Try again in a moment.' : errorText(err);
        this.running = null;
      },
    });
  }

  size(bytes: number | null): string {
    if (bytes === null) return '–';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  }
}
