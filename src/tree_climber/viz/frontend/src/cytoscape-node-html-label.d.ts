// TypeScript declarations for cytoscape-node-html-label

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
        tpl: (data: Record<string, unknown>) => string;
      }>,
      options?: { enablePointerEvents?: boolean }
    ): void;
  }
}

export {};
