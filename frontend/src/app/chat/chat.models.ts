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

/** One line of the backend's NDJSON stream. */
export type ChatEvent =
  | { type: 'thinking'; content: string }
  | { type: 'token'; content: string }
  | { type: 'tool_call'; name: string; arguments: { query?: string } }
  | { type: 'tool_result'; name: string; count: number }
  | { type: 'sources'; items: Source[] }
  | { type: 'done' }
  | { type: 'error'; message: string };
