import { TableResult } from './chat.models';

export interface ChartSpec {
  type: 'bar' | 'line';
  labelIndex: number; // column used for the x axis
  valueIndexes: number[]; // numeric columns drawn as series (max 3)
  order: number[]; // row order to draw (lines are sorted by date)
}

const DATE_LIKE = /^\d{4}(-\d{2}(-\d{2})?)?( |T|$)/; // 2020, 2020-03, 2020-03-14, 2020-03-14 10:00
const ID_NAME = /(^|_)id$|ID$/; // CustomerID, order_id: identifiers, not measures

/**
 * Pick a chart from the shape of the data, or null when a chart wouldn't help:
 *   one label column + numbers           -> bar (max 30 bars)
 *   a date/month label column + numbers  -> line, sorted by date (max 200 points)
 *   a single row, no numbers, no labels  -> no chart
 */
export function chartSpec(table: TableResult): ChartSpec | null {
  const { columns, rows } = table;
  if (rows.length < 2) return null;

  const isNumeric = (i: number) => rows.every((r) => r[i] === null || typeof r[i] === 'number');
  const indexes = columns.map((_, i) => i);
  const labels = indexes.filter((i) => !isNumeric(i));
  const values = indexes.filter((i) => isNumeric(i) && !ID_NAME.test(columns[i])).slice(0, 3);
  if (!values.length || !labels.length) return null;

  const dateLabel = labels.find((i) => rows.every((r) => DATE_LIKE.test(String(r[i] ?? ''))));
  if (dateLabel !== undefined) {
    if (rows.length > 200) return null;
    const order = rows.map((_, r) => r);
    order.sort((a, b) => String(rows[a][dateLabel]).localeCompare(String(rows[b][dateLabel])));
    return { type: 'line', labelIndex: dateLabel, valueIndexes: values, order };
  }

  if (rows.length > 30) return null;
  // Prefer a name over an ID for the axis (CompanyName rather than CustomerID), and the most specific
  // one when there are several (product_name rather than category).
  const named = labels.filter((i) => !ID_NAME.test(columns[i]));
  const labelIndex = named.length ? named[named.length - 1] : labels[0];
  return { type: 'bar', labelIndex, valueIndexes: values, order: rows.map((_, r) => r) };
}
