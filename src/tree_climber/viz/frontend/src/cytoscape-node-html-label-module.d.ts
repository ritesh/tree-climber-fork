// The package ships a global-script .d.ts, so declare it as an ES module here
declare module 'cytoscape-node-html-label' {
  const ext: (cy: any) => void;
  export default ext;
}
