// Node module-loader hook: stub out CSS imports so runtime JS that does
// `import './x.css'` (bundled by esbuild in real builds) loads under node.
export async function load(url, context, nextLoad) {
  if (url.endsWith('.css')) {
    return { format: 'module', source: 'export default {};', shortCircuit: true };
  }
  return nextLoad(url, context);
}
