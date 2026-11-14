import {
  AfterViewInit,
  Component,
  ElementRef,
  Input,
  NgZone,
  OnChanges,
  OnDestroy,
  ViewChild,
} from '@angular/core';
import { Chart, registerables } from 'chart.js';

import { ChartSpec } from '../chart-spec';
import { TableResult } from '../chat.models';

Chart.register(...registerables);

/** One Chart.js chart. Created outside Angular's zone, destroyed with the component. */
@Component({
  selector: 'app-result-chart',
  template: '<div class="chart-box"><canvas #canvas></canvas></div>',
  styles: ['.chart-box { position: relative; height: 280px; }'],
})
export class ResultChartComponent implements AfterViewInit, OnChanges, OnDestroy {
  @Input({ required: true }) table!: TableResult;
  @Input({ required: true }) spec!: ChartSpec;
  @ViewChild('canvas') private canvas?: ElementRef<HTMLCanvasElement>;

  private chart?: Chart;
  private readonly darkMode = window.matchMedia('(prefers-color-scheme: dark)');
  private readonly onThemeChange = () => this.draw(); // colours come from CSS variables

  constructor(private zone: NgZone) {}

  ngAfterViewInit(): void {
    this.draw();
    this.darkMode.addEventListener('change', this.onThemeChange);
  }

  ngOnChanges(): void {
    if (this.canvas) this.draw();
  }

  ngOnDestroy(): void {
    this.darkMode.removeEventListener('change', this.onThemeChange);
    this.chart?.destroy(); // otherwise the canvas stays registered and memory grows per message
  }

  /** PNG of the chart as a data URL (for the download button). */
  toPng(): string | undefined {
    return this.chart?.toBase64Image('image/png', 1);
  }

  private draw(): void {
    if (!this.canvas) return;
    const css = getComputedStyle(document.documentElement);
    const color = (name: string) => css.getPropertyValue(name).trim();
    const palette = [color('--chart-1'), color('--chart-2'), color('--chart-3')];
    const { columns, rows } = this.table;
    const { type, labelIndex, valueIndexes, order } = this.spec;

    // Chart.js animates with requestAnimationFrame; inside the zone every frame would trigger
    // Angular change detection for the whole page.
    this.zone.runOutsideAngular(() => {
      this.chart?.destroy();
      this.chart = new Chart(this.canvas!.nativeElement, {
        type,
        data: {
          labels: order.map((r) => String(rows[r][labelIndex] ?? '')),
          datasets: valueIndexes.map((col, i) => ({
            label: columns[col],
            data: order.map((r) => rows[r][col] as number | null),
            backgroundColor: palette[i % palette.length],
            borderColor: palette[i % palette.length],
            borderWidth: type === 'line' ? 2 : 0,
            pointRadius: type === 'line' ? 2 : 0,
            tension: 0.25,
          })),
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: valueIndexes.length > 1, labels: { color: color('--chart-text') } },
          },
          scales: {
            x: { ticks: { color: color('--chart-text'), maxRotation: 45 }, grid: { display: false } },
            y: { ticks: { color: color('--chart-text') }, grid: { color: color('--chart-grid') }, beginAtZero: true },
          },
        },
      });
    });
  }
}
