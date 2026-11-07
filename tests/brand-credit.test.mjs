import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const html = await readFile(new URL('../index.html', import.meta.url), 'utf8');
const start = html.indexOf('function BrandCredit(){');
const end = html.indexOf('\nfunction App(){', start);
assert.ok(start >= 0 && end > start, 'The fork credit component should exist');
const context = {
  React: { createElement: (tag, props, ...children) => ({ tag, props, children }) }
};
vm.runInNewContext(html.slice(start, end), context);

test('fork credit uses the branding template and links only Sean', () => {
  const credit = context.BrandCredit();
  assert.equal(credit.tag, 'footer');
  assert.equal(credit.props['aria-label'], 'Fork credit');
  assert.equal(credit.children.length, 3);
  assert.equal(credit.children[0], 'Adapted by ');
  assert.equal(credit.children[2], ' with ❤️');
  const link = credit.children[1];
  assert.equal(link.tag, 'a');
  assert.equal(link.children.join(''), 'Sean');
  assert.equal(link.props.href, 'https://www.linkedin.com/in/yuxiaoli/');
  assert.equal(link.props.target, '_blank');
  assert.equal(link.props.rel, 'noopener noreferrer');
});

test('fork credit is rendered once outside analysis and modal conditions', () => {
  assert.equal(html.split('React.createElement(BrandCredit)').length - 1, 1);
  assert.match(html, /\),\s*React\.createElement\(BrandCredit\),\s*showExport&&/);
  assert.match(html, /\.brand-credit\{margin-bottom:calc\(59px \+ env\(safe-area-inset-bottom\)\)\}/);
});
