// TypeScript declarations for cytoscape-node-html-label
import type cytoscape from 'cytoscape';

declare module 'cytoscape' {
  interface Core {
    nodeHtmlLabel(
      configs: Array<{
        query: string;
        halign?: string;
        valign?: string;
        halignBox?: string;
        valignBox?: string;
        cssClass?: string;
        tpl: (data: any) => string;
      }>,
      options?: { enablePointerEvents?: boolean }
    ): void;
  }
}
