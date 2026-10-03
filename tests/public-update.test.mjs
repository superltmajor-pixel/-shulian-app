import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { transformWithOxc } from 'vite';

const source = await readFile(new URL('../web/screens.jsx', import.meta.url), 'utf8');
function component(name) {
  const start = source.indexOf(`function ${name}(`);
  assert.ok(start >= 0);
  const next = source.indexOf('\nfunction ', start + 1);
  return source.slice(start, next < 0 ? undefined : next);
}
const code = component('SettingsMaintenanceSection') + '\n' + component('PublicDownloadUpdate');
const transformed = await transformWithOxc(code, 'settings-test.jsx', { jsx: { runtime: 'classic' } });
const context = vm.createContext({ React, SHULIAN_APP_VERSION: '0.26.0',
  currentUiLanguage: () => 'zh-CN', I: { save: () => null },
  uiT: (text, values = {}) => text.replace(/\{(\w+)\}/g, (_, key) => values[key] ?? ''),
});
vm.runInContext(transformed.code, context);
const render = status => renderToStaticMarkup(React.createElement(context.SettingsMaintenanceSection, {
  updateStatus: status, maintenance: {}, updatePercent: 0,
}));
const pending = render({ updateMode: 'download', publicReleaseReady: false });
assert.match(pending, /下载页尚未开放/);
assert.match(pending, /disabled=""[^>]*>下载页尚未开放/);
assert.doesNotMatch(pending, /后台更新到|正式版源码|最新版本/);
assert.match(pending, /webview-data/);
assert.match(pending, /LOCALAPPDATA/);
assert.match(pending, /不要先卸载/);
const published = render({ updateMode: 'download', publicReleaseReady: true });
assert.match(published, /<button[^>]*>打开公开下载页<\/button>/);
assert.doesNotMatch(published, /disabled=""[^>]*>打开公开下载页/);
assert.match(published, /尚未检查线上是否有新版本/);
const developer = render({ updateMode: 'source', packagerReady: true, updateAvailable: true, sourceVersion: '0.26.0' });
assert.match(developer, /后台更新到 v0.26.0/);
assert.doesNotMatch(developer, /打开公开下载页/);
console.log('Public update rendering: pending, published, local source and data instructions passed.');
