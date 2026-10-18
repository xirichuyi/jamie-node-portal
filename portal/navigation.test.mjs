import assert from 'node:assert/strict';
import { test, beforeEach } from 'node:test';
import {
  readView,
  tabFor,
  navigateTo,
  showDock,
  isAuthenticationView,
  authModeFor,
  afterLogin,
} from './navigation.ts';
let writes;
test('direct admin entry asks for login and returns to the requested management page', () => {
  for (const view of [
    'admin_users',
    'admin_content',
    'admin',
    'admin_tickets',
    'admin_logs',
    'operations',
  ]) {
    assert.equal(authModeFor(view), 'login');
    assert.equal(afterLogin(view), view);
  }
  assert.equal(authModeFor('home'), 'register');
  assert.equal(authModeFor('home', true), 'login');
  assert.equal(authModeFor('register', true), 'register');
  assert.equal(afterLogin('login'), 'home');
});
test('authentication, recovery, loading and forced password change never show the dock', () => {
  for (const view of [
    'home',
    'account',
    'redeem',
    'tickets',
    'subscription',
    'login',
    'register',
  ]) {
    assert.equal(isAuthenticationView(view, false), true);
    assert.equal(showDock(view, false, true), false);
  }
  assert.equal(showDock('recover', false, true), false);
  assert.equal(showDock('recover', true, true), false);
  for (const view of ['login', 'register']) {
    location.hash = '#/' + view;
    assert.equal(readView(), view);
    assert.equal(showDock(view, true, true), false);
  }
  assert.equal(showDock('home', true, false), false);
  assert.equal(showDock('security', true, true, true), false);
  for (const view of ['home', 'plans', 'guide', 'account'])
    assert.equal(showDock(view, true, true), true);
  assert.equal(showDock('plans', false, true), true);
});
beforeEach(() => {
  writes = [];
  globalThis.location = { hash: '' };
  globalThis.window = {
    history: Object.fromEntries(
      ['pushState', 'replaceState'].map((method) => [
        method,
        (state, _, hash) => {
          writes.push({ method, state, hash });
          location.hash = hash;
        },
      ]),
    ),
  };
});
test('four hubs resolve to their own active tab', () => {
  for (const view of ['home', 'plans', 'guide', 'account']) {
    location.hash = '#/' + view;
    assert.equal(readView(), view);
    assert.equal(tabFor(view), view);
  }
});
test('all secondary pages belong to a main tab', () => {
  for (const view of [
    'subscription',
    'security',
    'history',
    'help',
    'admin',
    'usage',
    'tickets',
    'sessions',
    'recover',
    'operations',
    'admin_tickets',
  ])
    assert.equal(tabFor(view), 'account');
  assert.equal(tabFor('redeem'), 'plans');
  assert.equal(tabFor('notices'), 'home');
  assert.equal(tabFor('status'), 'home');
});
test('unknown and prototype routes fall back safely', () => {
  for (const hash of [
    '#/missing',
    '#/__proto__',
    '#/constructor',
    '#<script>',
  ]) {
    location.hash = hash;
    assert.equal(readView(), 'home');
  }
  assert.equal(navigateTo('__proto__'), false);
  assert.equal(writes.length, 0);
});
test('navigation records a real history entry and its source', () => {
  location.hash = '#/plans';
  navigateTo('redeem');
  assert.deepEqual(writes[0], {
    method: 'pushState',
    state: { jamieFrom: 'plans' },
    hash: '#/redeem',
  });
  assert.equal(readView(), 'redeem');
});
test('same tab does not grow history', () => {
  location.hash = '#/account';
  navigateTo('account');
  assert.equal(writes.length, 0);
});
test('admin detail URLs retain the users route and management pages do not show user dock', () => {
  location.hash = '#/admin_users?user=test';
  assert.equal(readView(), 'admin_users');
  for (const view of [
    'admin',
    'admin_users',
    'admin_content',
    'admin_tickets',
    'operations',
  ])
    assert.equal(showDock(view, true, true), false);
});
test('password guard replaces route without adding a history entry', () => {
  navigateTo('security', true);
  assert.equal(writes[0].method, 'replaceState');
  assert.equal(readView(), 'security');
});
