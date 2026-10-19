// The package ships a global-script .d.ts, so declare it as an ES module here
declare module 'cytoscape-node-html-label' {
  import type cytoscape from 'cytoscape';
  const ext: (cy: typeof cytoscape) => void;
  export default ext;
}
