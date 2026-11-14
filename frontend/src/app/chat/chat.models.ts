export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

/** One line of the backend's NDJSON stream. */
export type ChatEvent =
  | { type: 'thinking'; content: string }
  | { type: 'token'; content: string }
  | { type: 'done' }
  | { type: 'error'; message: string };