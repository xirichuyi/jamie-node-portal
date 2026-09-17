import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import postcss from 'postcss';

const source = readFileSync(new URL('./main.tsx', import.meta.url), 'utf8');
const css = postcss.parse(
  readFileSync(new URL('./layout.css', import.meta.url), 'utf8'),
);
const declarations = (selector) => {
  const result = {};
  css.walkRules(selector, (rule) => {
    if (rule.parent.type === 'root')
      rule.walkDecls(({ prop, value }) => {
        result[prop] = value;
      });
  });
  return result;
};

test('dock mounts outside page content in a body portal, retaining visibility policy', () => {
  assert.match(
    source,
    /showDock\(view, !!me, loaded, !!me\?\.user\.must_change\)\s*&&\s*\(\s*<DockViewport>/,
  );
  const component = readFileSync(
    new URL('./dock-viewport.tsx', import.meta.url),
    'utf8',
  );
  assert.match(
    component,
    /createPortal\([\s\S]*?className="dock-viewport"[\s\S]*?document\.body/,
  );
  assert.doesNotMatch(component, /watchDockViewport|touchmove/);
});

test('viewport anchor stays fixed and independent of transformed glass surface', () => {
  const anchor = declarations('.dock-viewport');
  assert.equal(anchor.position, 'fixed');
  assert.equal(anchor['inset-inline'], '0');
  assert.equal(anchor.bottom, 'max(16px, env(safe-area-inset-bottom))');
  assert.equal(anchor['pointer-events'], 'none');
  for (const prop of [
    'transform',
    'filter',
    'backdrop-filter',
    'overflow',
    'animation',
  ]) {
    assert.equal(anchor[prop], undefined);
  }
  const surface = declarations('.dock-viewport > .dock');
  assert.equal(surface.position, 'relative');
  assert.equal(surface.transform, 'none');
  assert.equal(surface.inset, 'auto');
  assert.equal(surface['pointer-events'], 'auto');
});

test('mobile content reserves dock space and device safe area', () => {
  const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
  assert.match(html, /viewport-fit=cover/);
  let padding;
  css.walkAtRules('media', (media) => {
    if (media.params === '(max-width: 700px)') {
      media.walkRules('main.wide', (rule) =>
        rule.walkDecls('padding', (decl) => {
          padding = decl.value;
        }),
      );
    }
  });
  assert.equal(padding, '96px 22px calc(118px + env(safe-area-inset-bottom))');
});
