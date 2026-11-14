import { Component, OnInit } from '@angular/core';
import { forkJoin } from 'rxjs';

import { AdminService, Resources, RowRule, errorText } from '../admin.service';

/**
 * Row-level rules: "in <table>, <column> must match the user's <attribute>".
 * They apply to every non-admin user; a user without the attribute sees no rows of that table.
 */
@Component({
  selector: 'app-admin-rules',
  templateUrl: './rules.component.html',
  styleUrls: ['../admin.scss'],
})
export class RulesComponent implements OnInit {
  rules: RowRule[] = [];
  resources?: Resources;
  error = '';
  adding = false;
  draft = { kind: 'spreadsheet' as 'spreadsheet' | 'database', source: '', table: '', column: '', attribute: '' };

  constructor(private admin: AdminService) {}

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    forkJoin({ rules: this.admin.rules(), resources: this.admin.resources() }).subscribe({
      next: ({ rules, resources }) => {
        this.rules = rules;
        this.resources = resources;
      },
      error: (err) => (this.error = errorText(err)),
    });
  }

  /** Tables to pick from for the chosen kind/database. */
  get tables(): string[] {
    const columns = this.resources?.columns;
    if (!columns) return [];
    const map = this.draft.kind === 'spreadsheet' ? columns.spreadsheet : columns.database[this.draft.source] ?? {};
    return Object.keys(map).sort();
  }

  get columns(): string[] {
    const columns = this.resources?.columns;
    if (!columns || !this.draft.table) return [];
    const map = this.draft.kind === 'spreadsheet' ? columns.spreadsheet : columns.database[this.draft.source] ?? {};
    return map[this.draft.table] ?? [];
  }

  start(): void {
    this.adding = true;
    this.draft = { kind: 'spreadsheet', source: '', table: '', column: '', attribute: '' };
  }

  changeKind(): void {
    this.draft.source = this.draft.kind === 'database' ? this.resources?.database[0] ?? '' : '';
    this.draft.table = '';
    this.draft.column = '';
  }

  save(): void {
    this.error = '';
    this.admin.addRule(this.draft).subscribe({
      next: () => {
        this.adding = false;
        this.load();
      },
      error: (err) => (this.error = errorText(err)),
    });
  }

  remove(rule: RowRule): void {
    if (!confirm(`Delete the rule on ${rule.table_name}.${rule.column_name}? Restricted users then see all its rows.`)) return;
    this.admin.deleteRule(rule.id).subscribe({
      next: () => this.load(),
      error: (err) => (this.error = errorText(err)),
    });
  }
}
