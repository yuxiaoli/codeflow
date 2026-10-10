import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const html = await readFile(new URL('../index.html', import.meta.url), 'utf8');
const marker = html.indexOf('var exportFmt = autoExportFormatRef.current;');
assert.ok(marker >= 0, 'URL export effect should exist');
const start = html.lastIndexOf('    useEffect(function(){', marker);
const end = html.indexOf('\n    function parseUrl(', marker);
const refStart = html.indexOf('var autoExportFormatRef=useRef(');
assert.ok(refStart >= 0, 'URL export request should be captured at mount');
const refEnd = html.indexOf(';', refStart) + 1;
const source = html.slice(refStart, refEnd) + '\n' + html.slice(start, end);

function setup(format, options = {}) {
  const pending = new Map();
  const exports = [];
  const views = [];
  let nextTimer = 0;
  let effect;
  let rendered = false;
  const context = {
    URLSearchParams,
    window: { location: { search: '?export=' + format } },
    data: options.data === undefined ? { files: [] } : options.data,
    graphConfig: { vizType: options.view || 'graph' },
    architectureRenderRef: { current: { querySelector: () => rendered ? {} : null } },
    useRef: (value) => ({ current: value }),
    useEffect: (callback) => { effect = callback; },
    setGraphConfig: (update) => views.push(update(context.graphConfig).vizType),
    setTimeout: (callback) => { pending.set(++nextTimer, callback); return nextTimer; },
    clearTimeout: (id) => pending.delete(id),
    exportJSON: () => exports.push('json'),
    generateReport: (format) => exports.push(format),
    exportSVG: () => exports.push('svg'),
    exportPDF: () => exports.push('pdf'),
    downloadMermaid: () => exports.push('mermaid'),
    downloadArchitectureSVG: () => exports.push('diagram')
  };
  vm.runInNewContext(source, context);
  return {
    context, pending, exports, views,
    run: () => effect(),
    render: () => { rendered = true; },
    tick: () => {
      const [id, callback] = pending.entries().next().value;
      pending.delete(id);
      callback();
    }
  };
}

test('URL diagram export opens Block Diagram before scheduling a download', () => {
  const app = setup('diagram');
  app.run();
  assert.deepEqual(app.views, ['architecture']);
  assert.equal(app.pending.size, 0);
  assert.equal(app.context.window.__hasAutoExported, undefined);
});

test('URL diagram export waits for the rendered SVG and downloads once', () => {
  const app = setup('diagram', { view: 'architecture' });
  app.run();
  app.tick();
  assert.deepEqual(app.exports, []);
  assert.equal(app.pending.size, 1);
  app.render();
  app.tick();
  assert.deepEqual(app.exports, ['diagram']);
  app.run();
  assert.equal(app.pending.size, 0);
});

test('URL export cleanup cancels a pending render retry', () => {
  const app = setup('diagram', { view: 'architecture' });
  const cleanup = app.run();
  app.tick();
  cleanup();
  assert.equal(app.pending.size, 0);
  assert.deepEqual(app.exports, []);
});

test('URL diagram export reports a missing render after a bounded wait', () => {
  const app = setup('diagram', { view: 'architecture' });
  app.run();
  for (let retry = 0; retry <= 60; retry++) app.tick();
  assert.deepEqual(app.exports, ['diagram']);
  assert.equal(app.pending.size, 0);
});

test('URL JSON export preserves the current visualization and only downloads once', () => {
  const app = setup('json');
  app.run();
  app.tick();
  assert.deepEqual(app.exports, ['json']);
  assert.deepEqual(app.views, []);
  app.run();
  assert.equal(app.pending.size, 0);
});

test('URL export waits for analysis data', () => {
  const app = setup('diagram', { data: null });
  app.run();
  assert.equal(app.pending.size, 0);
  assert.deepEqual(app.views, []);
  assert.deepEqual(app.exports, []);
});

test('URL export survives repository analysis rewriting the address', () => {
  const app = setup('json');
  app.context.window.location.search = '?repo=octocat%2FHello-World';
  app.run();
  app.tick();
  assert.deepEqual(app.exports, ['json']);
});
