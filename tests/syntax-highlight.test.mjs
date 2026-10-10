import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const html = await readFile(new URL('../index.html', import.meta.url), 'utf8');
const start = html.indexOf('    function highlightSyntax(code,filename){');
const end = html.indexOf('\n    function folderSourceIsLive(){', start);
assert.ok(start >= 0 && end > start, 'syntax highlighter should exist');
const context = {};
vm.runInNewContext(html.slice(start, end), context);

function visibleSource(lines) {
  return lines.join('\n')
    .replace(/<span\b[^>]*>/g, '').replace(/<\/span>/g, '')
    .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
}

for (const filename of ['example.js', 'example.py', 'Example.java', 'example.rb', 'example.php']) {
  test('highlighting preserves numbers, strings and comments in ' + filename, () => {
    const code = "class Example {\n  return add (1, 2); // class 3\n  value = 'class 4 <tag> & more';\n  # return 5\n}";
    const lines = context.highlightSyntax(code, filename);
    assert.equal(visibleSource(lines), code);
    assert.ok(lines.some((line) => line.includes('class="syn-num"')));
  });
}

test('highlighting preserves source HTML attributes and whitespace before types', () => {
  for (const [filename, code] of [
    ['example.html', '<div class="card1" data-count="2">class 3 & text</div>'],
    ['example.ts', 'const user:   User = buildUser (1);']
  ]) {
    assert.equal(visibleSource(context.highlightSyntax(code, filename)), code);
  }
});
