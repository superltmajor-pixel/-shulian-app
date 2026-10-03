// Execute the shipped loader, without React rendering or network access.
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const profiles = JSON.parse(fs.readFileSync(0, 'utf8'));
const app = fs.readFileSync(path.join(root, 'web/app.jsx'), 'utf8');
const loader = app.slice(app.indexOf('async function loadRoleLibraryBeforeRender()'), app.indexOf('function renderShulianApp()'));
const context = vm.createContext({window: {}, console,
  fetch: async () => ({ok: true, json: async () => ({roles: profiles.map(frontend => ({frontend}))})})});
vm.runInContext(fs.readFileSync(path.join(root, 'web/data.jsx'), 'utf8'), context);
vm.runInContext(`const API_BASE=''; const CHARACTER_ACCENTS={};
  const CHARACTER_SELF_VOCATIVES={}; const COMPANION_CALIBRATIONS={};
  let pendingRoleArchiveRoles=[]; ${loader}`, context);
vm.runInContext('loadRoleLibraryBeforeRender()', context).then(() => {
  process.stdout.write(vm.runInContext(`JSON.stringify({roster:ROSTER, quizzes:QUIZ_BANK,
    palettes:CHARACTER_ACCENTS, forms:ROSTER.map(c => c.forms.map((_, i) => mergeForm(c, i)))})`, context));
}).catch(error => {console.error(error); process.exitCode = 1;});
