export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

/** A passage the answer cites as [number]. */
export interface Source {
  number: number;
  source: string;
  page: number | null;
  heading: string | null;
  snippet: string;
}

/** Result of a SQL query over the spreadsheets or a database. */
export interface TableResult {
  database?: string; // SQL Server database; absent for spreadsheet results
  sql: string;
  columns: string[];
  rows: (string | number | null)[][];
  truncated: boolean;
  restricted?: string[]; // tables limited to this user's rows by row rules
}

/** One line of the backend's NDJSON stream. */
export type ChatEvent =
  | { type: 'thinking'; content: string }
  | { type: 'token'; content: string }
  | { type: 'tool_call'; name: string; arguments: { query?: string; database?: string; sql?: string } }
  | { type: 'tool_result'; name: string; count: number; ok: boolean }
  | ({ type: 'table' } & TableResult)
  | { type: 'sources'; items: Source[] }
  | { type: 'done' }
  | { type: 'error'; message: string };

/** A message as shown on screen and saved: the API fields plus display data. */
export interface UiMessage extends ChatMessage {
  thinking?: string;
  error?: boolean;
  steps?: string[]; // e.g. 'Searched: "clause 6.2" (5 passages)'
  sources?: Source[];
  tables?: TableResult[];
}

export interface ConversationSummary {
  id: string;
  title: string;
  updated: string; // ISO date
}

export interface Conversation extends ConversationSummary {
  created: string;
  messages: UiMessage[];
}
