import { Pipe, PipeTransform } from '@angular/core';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import DOMPurify from 'dompurify';
import { marked } from 'marked';

// Links the model writes open in a new tab and can't reach back into this page.
DOMPurify.addHook('afterSanitizeAttributes', (node) => {
  if (node.tagName === 'A' && node.hasAttribute('href')) {
    node.setAttribute('target', '_blank');
    node.setAttribute('rel', 'noopener noreferrer');
  }
});

const CITATION = /\[(\d+(?:\s*,\s*\d+)*)\]/g; // [1] or [2, 3]

/**
 * Model output -> safe HTML. Order matters: Markdown -> HTML, then DOMPurify removes scripts and event
 * handlers, and only then Angular is told to trust it. Model text is untrusted: documents can contain
 * prompt injection that makes the model write HTML.
 *
 * Pure pipe: it only runs again when the text changes (once per streamed token, not on every check).
 */
@Pipe({ name: 'markdown' })
export class MarkdownPipe implements PipeTransform {
  constructor(private sanitizer: DomSanitizer) {}

  transform(text: string | null | undefined): SafeHtml {
    if (!text) return '';
    const html = marked.parse(text, { async: false, gfm: true, breaks: true }) as string;
    const cited = html.replace(CITATION, (_match, numbers: string) =>
      numbers
        .split(',')
        .map((n) => `<a class="cite" data-n="${n.trim()}" role="button">[${n.trim()}]</a>`)
        .join(''),
    );
    const clean = DOMPurify.sanitize(cited, { USE_PROFILES: { html: true } });
    return this.sanitizer.bypassSecurityTrustHtml(clean);
  }
}
