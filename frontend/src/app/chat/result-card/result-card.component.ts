import { Component, HostListener, Input, OnChanges, ViewChild } from '@angular/core';

import { ChartSpec, chartSpec } from '../chart-spec';
import { TableResult } from '../chat.models';
import { ResultChartComponent } from '../result-chart/result-chart.component';

type Cell = string | number | null;

/** A query result: chart or table, sortable, with CSV / PNG / copy and a full-screen view. */
@Component({
  selector: 'app-result-card',
  templateUrl: './result-card.component.html',
  styleUrls: ['./result-card.component.scss'],
})
export class ResultCardComponent implements OnChanges {
  @Input({ required: true }) table!: TableResult;
  @ViewChild(ResultChartComponent) private chart?: ResultChartComponent;

  spec: ChartSpec | null = null;
  view: 'chart' | 'table' = 'table';
  rows: Cell[][] = [];
  sortColumn = -1;
  sortDescending = false;
  expanded = false;
  copied = false;

  ngOnChanges(): void {
    this.spec = chartSpec(this.table);
    this.view = this.spec ? 'chart' : 'table';
    this.sortColumn = -1;
    this.rows = [...this.table.rows];
  }

  get source(): string {
    return this.table.database ?? 'spreadsheets';
  }

  sortBy(column: number): void {
    this.sortDescending = this.sortColumn === column ? !this.sortDescending : false;
    this.sortColumn = column;
    const direction = this.sortDescending ? -1 : 1;
    this.rows = [...this.table.rows].sort((a, b) => direction * compare(a[column], b[column]));
  }

  isNumber(value: unknown): boolean {
    return typeof value === 'number';
  }

  formatCell(value: Cell): string {
    if (value === null) return '';
    return typeof value === 'number' ? value.toLocaleString(undefined, { maximumFractionDigits: 2 }) : value;
  }

  downloadCsv(): void {
    const quote = (v: Cell) => {
      const text = v === null ? '' : String(v);
      return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
    };
    const lines = [this.table.columns, ...this.rows].map((row) => row.map(quote).join(','));
    // BOM so Excel opens UTF-8 (é, ü) correctly
    this.download(new Blob(['﻿' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' }), 'csv');
  }

  downloadPng(): void {
    const url = this.chart?.toPng();
    if (url) this.download(url, 'png');
  }

  async copy(): Promise<void> {
    // Tab-separated: pastes into Excel as columns
    const text = [this.table.columns, ...this.rows].map((row) => row.map((v) => v ?? '').join('\t')).join('\n');
    await navigator.clipboard.writeText(text);
    this.copied = true;
    setTimeout(() => (this.copied = false), 1500);
  }

  @HostListener('document:keydown.escape')
  close(): void {
    this.expanded = false;
  }

  private download(content: Blob | string, extension: string): void {
    const url = typeof content === 'string' ? content : URL.createObjectURL(content);
    const link = document.createElement('a');
    link.href = url;
    link.download = `result-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.${extension}`;
    link.click();
    if (typeof content !== 'string') URL.revokeObjectURL(url);
  }
}

function compare(a: Cell, b: Cell): number {
  if (a === null) return 1; // empty cells last
  if (b === null) return -1;
  if (typeof a === 'number' && typeof b === 'number') return a - b;
  return String(a).localeCompare(String(b), undefined, { numeric: true });
}
