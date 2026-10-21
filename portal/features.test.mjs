import assert from 'node:assert/strict';
import { test, after } from 'node:test';
import { createServer } from 'vite';
import { renderToStaticMarkup } from 'react-dom/server';
import React from 'react';
import QRCode from 'qrcode';
const vite = await createServer({
  configFile: 'vite.portal.config.ts',
  server: { middlewareMode: true },
  appType: 'custom',
});
after(() => vite.close());
const features = {
  ...await vite.ssrLoadModule('/portal/features.tsx'),
  ...await vite.ssrLoadModule('/portal/account-features.tsx'),
  ...await vite.ssrLoadModule('/portal/admin-operations.tsx'),
};
const journeys = await vite.ssrLoadModule('/portal/journeys.tsx');
const content = await vite.ssrLoadModule('/portal/content.tsx');
const apiModule = await vite.ssrLoadModule('/portal/api.ts');
const experience = await vite.ssrLoadModule('/portal/experience.ts');
const authentication = await vite.ssrLoadModule('/portal/auth.tsx');
const users = await vite.ssrLoadModule('/portal/admin-users.tsx');
const notices = await vite.ssrLoadModule('/portal/notice-entry.tsx');
const support = await vite.ssrLoadModule('/portal/admin-support.tsx');
const cards = await vite.ssrLoadModule('/portal/card-entry.tsx');
const payments = await vite.ssrLoadModule('/portal/payments.tsx');
const cardAdmin = await vite.ssrLoadModule('/portal/admin-cards.tsx');
const installGuide = await vite.ssrLoadModule('/portal/install.tsx');
void test('install guidance recognizes iPad desktop UA and stays hidden on excluded pages', () => {
  assert.equal(installGuide.installPlatform('Mozilla iPhone', 5), 'ios');
  assert.equal(installGuide.installPlatform('Mozilla Macintosh Safari', 5), 'ios');
  assert.equal(installGuide.installPlatform('Mozilla Macintosh Safari', 0), 'desktop');
  assert.equal(installGuide.installPlatform('Mozilla Android Chrome', 5), 'android');
  assert.equal(renderToStaticMarkup(React.createElement(installGuide.InstallGuide, { visible: false, promote: true })), '');
});
void test('payment purchase requires an explicit user action and orders show confirmation status', () => {
  const button = renderToStaticMarkup(React.createElement(payments.PurchaseButton, { planId: 'test', label: '测试套餐', price: 3000000, navigate: () => {} }));
  assert.match(button, /购买套餐/);
  assert.doesNotMatch(button, /href=/);
  const orders = renderToStaticMarkup(React.createElement(payments.OrdersPage));
  assert.match(orders, /付款确认后自动更新/);
  assert.doesNotMatch(orders, /sk_live_|whsec_/);
});
void test('card links keep the credential in the fragment and validate pasted values', () => {
  const code = '01234567-89ABCDEF-01234567-89ABCDEF';
  const link = cards.cardLink(code, 'https://example.test');
  assert.equal(new URL(link).search, '');
  assert.equal(cards.parseCard(link), code);
  assert.equal(cards.parseCard(' ' + code + ' '), code);
  assert.throws(() => cards.parseCard('unrelated clipboard content'));
  assert.throws(() => cards.parseCard('https://example.test/?code=' + code));
  const markup = renderToStaticMarkup(React.createElement(cards.PasteCard, {onCode: () => {}}));
  assert.match(markup, /从剪贴板粘贴/);
  assert.match(markup, /type="button"/);
});
void test('opening a card link removes it from the URL but keeps it through login in memory', () => {
  const code = '01234567-89ABCDEF-01234567-89ABCDEF';
  const oldLocation = globalThis.location, oldWindow = globalThis.window;
  try {
    const url = new URL(cards.cardLink(code, 'https://example.test'));
    globalThis.location = url;
    globalThis.window = { dispatchEvent: () => {}, history: { state: null, replaceState: (_state, _unused, target) => { url.href = new URL(target, url).href; } } };
    cards.captureCardLink();
    assert.equal(url.hash, '#/redeem');
    assert.equal(cards.pendingCard(), code);
    assert.throws(() => cards.parseCard(cards.cardLink(code, 'https://untrusted.test')));
    cards.clearPendingCard();
    assert.equal(cards.pendingCard(), '');
  } finally {
    if (oldLocation === undefined) delete globalThis.location; else globalThis.location = oldLocation;
    if (oldWindow === undefined) delete globalThis.window; else globalThis.window = oldWindow;
  }
});
test('account deletion is an explicit action and pending deletion is visible to staff', () => {
  const self = renderToStaticMarkup(React.createElement(features.DeleteAccount, {username:'test@example.com'}));
  const admin = renderToStaticMarkup(React.createElement(features.DeleteAccount, {username:'test@example.com',userId:'test-id'}));
  assert.match(self, /注销账号/);
  assert.match(admin, /删除账号/);
  const state = renderToStaticMarkup(React.createElement(users.UserStatus, {member:{primary_state:'disabled',sync_state:'synced',deleting:1}}));
  assert.match(state, /删除处理中/);
});
test('usage windows remove uncollected leading dates but preserve real zero and internal gaps', () => {
  const rows = [null, null, 0, null, 1024].map((bytes, i) => ({ day: `2026-09-${10+i}`, bytes, partial: false }));
  for (const compact of [true, false]) {
    assert.deepEqual(features.usageWindow(rows, compact).map(d => d.bytes), [0, null, 1024]);
    assert.deepEqual(features.usageWindow(rows.slice(0, 2), compact), []);
  }
});
test('secondary pages hide the notice strip and help avoids promotional heading', () => {
  const html = renderToStaticMarkup(React.createElement(notices.NoticeEntry, {
    notices: [{ id:'published', title:'Notice', body:'Body', published:1, pinned:1, created:1, updated:1, revision:1, category:'info' }],
    ready:true, showStrip:false, navigate:()=>{},
  }));
  assert.doesNotMatch(html, /entry-notice/);
  const help = renderToStaticMarkup(React.createElement(content.HelpPage, {navigate:()=>{}}));
  assert.doesNotMatch(help, /遇到问题，先从这里开始|导入、续费和连接问题的常见解答/);
});
test('email recovery is the default and retains a legacy recovery entry', () => {
  const html = renderToStaticMarkup(React.createElement(features.Recover, {navigate: () => {}}));
  assert.match(html, /注册邮箱/);
  assert.match(html, /邮箱验证码/);
  assert.match(html, /发送验证码/);
  assert.match(html, /one-time-code/);
  assert.match(html, /使用恢复码找回/);
});
test('package accounting exposes independent expirations without promising perpetual rollover', () => {
  const html = renderToStaticMarkup(React.createElement(features.PackageBalances, {
    packages: [{id:'one', label:'Test package',kind:'base',granted:1024,spent:0,remaining:1024,expires:2000000000,status:'active'},
      {id:'two',label:'Top up',kind:'addon',granted:1024,spent:1024,remaining:0,expires:2000000000,status:'exhausted'}],
  }));
  assert.match(html,/扣除顺序 1/);
  assert.match(html,/加流量包/);
  assert.match(html,/已用完/);
  assert.doesNotMatch(html,/叠加流量和有效期/);
});
test('permanent recurring plans show renewal without a fake expiry date', async () => {
  const cycles = await vite.ssrLoadModule('/portal/cycles.tsx');
  const rule = {permanent:1, reset_period:'monthly', days:1};
  assert.equal(cycles.expiryLabel(cycles.FOREVER), '永久有效');
  assert.equal(experience.remainingTime(cycles.FOREVER), '永久有效');
  const html = renderToStaticMarkup(React.createElement(authentication.ActivationSummary, {plan:{...rule,label:'Monthly',quota:100*1024**3}}));
  assert.match(html, /永久有效/);
  assert.match(html, /按开通日每月重置/);
  const fields = renderToStaticMarkup(React.createElement(cycles.TermsFields, {value:{...rule,quota_gib:100}, onChange(){}}));
  assert.match(fields, /0 = 永久/);
  assert.match(fields, /每月（按开通日）/);
  assert.deepEqual(cycles.termsBody({quota_gib:0.5,days:0}), {quota_gib:0.5,days:0,permanent:true,reset_period:'never',reset_interval:30});
  assert.doesNotMatch(fields, /每月几日|固定日期/);
  const balances = renderToStaticMarkup(React.createElement(features.PackageBalances, {packages:[{...rule,id:'cycle',label:'Monthly',kind:'base',granted:100,spent:100,remaining:0,expires:cycles.FOREVER,next_reset:2000000000,status:'exhausted'}]}));
  assert.match(balances, /下次重置/);
  assert.doesNotMatch(balances, /9999/);
});
test('admin support exposes card lookup and credential-free login diagnostics', () => {
  const ledger = renderToStaticMarkup(
    React.createElement(cardAdmin.CardLedger, { batch: null, onClearBatch: () => {} }),
  );
  assert.match(ledger, /卡密 \/ 尾号 \/ 兑换链接 \/ 账号 \/ 备注 \/ 卡名/);
  assert.doesNotMatch(ledger, /最近 500 张/);
  const diagnosis = renderToStaticMarkup(
    React.createElement(support.LoginDiagnosis),
  );
  assert.match(diagnosis, /登录问题诊断/);
  assert.match(diagnosis, /不查看或保存用户密码/);
});
test('user workspace starts with search, status filters and no destructive row actions', () => {
  const html = renderToStaticMarkup(React.createElement(users.UserManager, {}));
  for (const label of [
    '用户管理',
    '搜索全部用户',
    '剩余 / 总流量',
    '流量耗尽',
    '同步异常',
  ])
    assert.ok(html.includes(label));
  assert.doesNotMatch(html, /临时密码/);
  assert.doesNotMatch(html, /重置密码/);
  const state = renderToStaticMarkup(
    React.createElement(users.UserStatus, {
      member: { primary_state: 'disabled', sync_state: 'pending' },
    }),
  );
  assert.match(state, /账号停用/);
  assert.match(state, /待同步/);
});
test('admin navigation separates users, cards, tickets, content and return to user site', () => {
  const html = renderToStaticMarkup(
    React.createElement(journeys.AdminNavigation, {
      view: 'admin_users',
      navigate: () => {},
    }),
  );
  for (const label of [
    '概览',
    '用户',
    '卡密',
    '工单',
    '公告与套餐',
    '返回用户端',
  ])
    assert.ok(html.includes(label));
  assert.doesNotMatch(html, /发卡与用户/);
});
test('public notice entry is visible without login; drafts stay hidden and revision changes unread identity', () => {
  const make = (id, published, pinned, updated) => ({
    id,
    title: id,
    body: '纯文本公告',
    published,
    pinned,
    updated,
    created: updated,
    revision: 1,
    category: 'info',
  });
  const list = [
    make('draft', 0, 1, 100),
    make('latest', 1, 0, 20),
    make('important', 1, 1, 10),
  ];
  assert.deepEqual(
    notices.publicNotices(list).map((n) => n.id),
    ['important', 'latest'],
  );
  assert.notEqual(
    notices.noticeKey(list[2]),
    notices.noticeKey({ ...list[2], revision: 2 }),
  );
  const html = renderToStaticMarkup(
    React.createElement(notices.NoticeEntry, {
      notices: list,
      ready: true,
      navigate: () => {},
    }),
  );
  assert.match(html, /important/);
  assert.match(html, /全部公告/);
  assert.doesNotMatch(html, /draft/);
  assert.doesNotMatch(html, /role="dialog"/);
  const listHtml = renderToStaticMarkup(React.createElement(content.Announcements, { notices: list }));
  assert.doesNotMatch(listHtml, /draft/);
  assert.match(listHtml, /<details/);
  assert.match(listHtml, /<summary/);
  assert.doesNotMatch(listHtml, /<details[^>]* open/);
  assert.equal(
    renderToStaticMarkup(
      React.createElement(notices.NoticeEntry, {
        notices: [list[0]],
        ready: true,
        navigate: () => {},
      }),
    ),
    '',
  );
});
test('activation starts with only a card; login remains a separate credential form', () => {
  const render = (mode) =>
    renderToStaticMarkup(
      React.createElement(authentication.AuthFlow, {
        mode,
        navigate: () => {},
        onSuccess: async () => {},
      }),
    );
  const signup = render('register');
  assert.match(signup, /用卡密开通账号/);
  assert.match(signup, /name="code"/);
  assert.doesNotMatch(signup, /name="password"/);
  assert.match(signup, /验证不扣卡、不计时/);
  assert.match(signup, /已经开通过？登录账号/);
  const login = render('login');
  assert.match(login, /name="username"/);
  assert.match(login, /name="password"/);
  assert.doesNotMatch(login, /name="code"/);
  assert.match(login, /忘记密码/);
});
test('activation summary exposes the real quota, duration and start-time rule', () => {
  const html = renderToStaticMarkup(
    React.createElement(authentication.ActivationSummary, {
      plan: { label: '测试套餐', quota: 100 * 1024 ** 3, days: 30 },
    }),
  );
  for (const value of [
    '测试套餐',
    '100',
    'GiB',
    '30',
    '开通后开始计时',
    '不会扣卡',
  ])
    assert.ok(html.includes(value));
});
test('expiry uses minutes and hours on the last day, never a misleading full day', () => {
  const now = 100000;
  assert.equal(experience.remainingTime(0, now), '尚未开通');
  assert.equal(experience.remainingTime(now, now), '已到期');
  assert.equal(experience.remainingTime(now + 20, now), '不足 1 分钟');
  assert.equal(experience.remainingTime(now + 300, now), '5 分钟');
  assert.equal(experience.remainingTime(now + 3601, now), '2 小时');
  assert.equal(experience.remainingTime(now + 86400, now), '1 天');
});
test('ambiguous prices never invent a currency and remaining quota preserves existing usage', () => {
  for (const value of ['', '30', ' 30.00 '])
    assert.equal(experience.priceText(value), '价格请咨询管理员');
  assert.equal(experience.priceText('¥30 / 90 天'), '¥30 / 90 天');
  assert.equal(experience.priceText('US$5'), 'US$5');
  assert.equal(experience.remainingAfter(100, 30), 70);
  assert.equal(experience.remainingAfter(100, 120), 0);
  assert.equal(experience.remainingAfter(100, null), null);
  assert.equal(experience.remainingAfter(100, undefined), null);
});
test('tutorial preferences accept only known devices and valid steps, including blocked storage', () => {
  const original = globalThis.sessionStorage;
  try {
    globalThis.sessionStorage = {
      getItem: () => JSON.stringify({ device: 'ios', step: 2 }),
    };
    assert.deepEqual(experience.readGuide(), { device: 'ios', step: 2 });
    for (const value of [
      'broken',
      '{"device":"unknown","step":0}',
      '{"device":"ios","step":10}',
    ]) {
      globalThis.sessionStorage = { getItem: () => value };
      assert.equal(experience.readGuide(), null);
    }
    globalThis.sessionStorage = {
      getItem: () => {
        throw new Error('denied');
      },
    };
    assert.equal(experience.readGuide(), null);
  } finally {
    globalThis.sessionStorage = original;
  }
});
test('simultaneous reads share a request but completed responses are not cached', async () => {
  const original = globalThis.fetch;
  let finish, calls = 0;
  try {
    globalThis.fetch = () => {
      calls++;
      return new Promise(resolve => { finish = resolve; });
    };
    const first = apiModule.api('test/shared');
    const second = apiModule.api('test/shared');
    assert.equal(calls, 1);
    finish(Response.json({ value: 1 }));
    assert.deepEqual(await Promise.all([first, second]), [{ value: 1 }, { value: 1 }]);
    const fresh = apiModule.api('test/shared');
    assert.equal(calls, 2);
    finish(Response.json({ value: 2 }));
    assert.deepEqual(await fresh, { value: 2 });
  } finally { globalThis.fetch = original; }
});
test('mutation boundaries prevent sharing old account reads', async () => {
  const original = globalThis.fetch;
  const reads = [];
  try {
    globalThis.fetch = (_url, options) => options.method === 'POST'
      ? Promise.resolve(Response.json({ ok: true }))
      : new Promise(resolve => reads.push(resolve));
    const previous = apiModule.api('test/account');
    await apiModule.api('test/logout', {});
    const current = apiModule.api('test/account');
    assert.equal(reads.length, 2);
    reads[0](Response.json({ user: 'old' }));
    await previous;
    const sameGeneration = apiModule.api('test/account');
    assert.equal(reads.length, 2, 'an old response must not evict the new request');
    reads[1](Response.json({ user: null }));
    assert.deepEqual(await Promise.all([current, sameGeneration]), [{ user: null }, { user: null }]);
  } finally { globalThis.fetch = original; }
});
test('last reads are remembered for remounts and dropped at every mutation', async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async (_url, options) => Response.json(
      options.method === 'POST' ? { ok: true } : { value: 'fresh' },
    );
    await apiModule.api('test/remember');
    assert.deepEqual(apiModule.lastRead('test/remember'), { value: 'fresh' });
    await apiModule.api('test/logout', {});
    assert.equal(apiModule.lastRead('test/remember'), null);
  } finally { globalThis.fetch = original; }
});
test('failed reads leave no rejected response cache', async () => {
  const original = globalThis.fetch;
  let calls = 0;
  try {
    globalThis.fetch = async () => ++calls === 1
      ? Response.json({ error: 'login required' }, { status: 401 })
      : Response.json({ ok: true });
    await assert.rejects(apiModule.api('test/recover'), { status: 401 });
    assert.deepEqual(await apiModule.api('test/recover'), { ok: true });
    assert.equal(calls, 2);
  } finally { globalThis.fetch = original; }
});
test('read-only loads retry a transient gateway failure', async () => {
  const original = globalThis.fetch;
  let calls = 0;
  try {
    globalThis.fetch = async () =>
      ++calls === 1
        ? new Response('<html>Unavailable</html>', { status: 502 })
        : Response.json({ ok: true });
    assert.deepEqual(await apiModule.api('test'), { ok: true });
    assert.equal(calls, 2);
  } finally {
    globalThis.fetch = original;
  }
});
test('mutations never auto-retry and HTML errors become readable messages', async () => {
  const original = globalThis.fetch;
  let calls = 0;
  try {
    globalThis.fetch = async () => {
      calls++;
      return new Response('<html>Unavailable</html>', { status: 503 });
    };
    await assert.rejects(
      apiModule.api('redeem', { code: 'fixture' }),
      (e) => e.status === 503 && e.message === '服务暂时不可用，请稍后重试。',
    );
    assert.equal(calls, 1);
  } finally {
    globalThis.fetch = original;
  }
});
const navigate = () => {};
const subscription = {
  quota: 100 * 1024 ** 3,
  used: 20 * 1024 ** 3,
  expires: Date.now() / 1000 + 30 * 86400,
  url: 'https://sub.chuyi.uk/sub/fake-test-only',
  pending: false,
  rotating: false,
  sync_error: null,
  usage_error: null,
  enabled: true,
  plan_name: '标准月卡',
};
test('home changes its primary task for new, active and expired subscribers', () => {
  const render = (s) =>
    renderToStaticMarkup(
      React.createElement(journeys.Dashboard, {
        s,
        incidents: [],
        username: 'Test',
        content: null,
        navigate,
        refresh: () => {},
        busy: false,
      }),
    );
  const fresh = render({ ...subscription, quota: 0, url: null });
  assert.match(fresh, /有卡密，即可开始/);
  assert.ok(!fresh.includes('quota-value'));
  const active = render(subscription);
  assert.match(active, /quota-value/);
  assert.match(active, /连接你的设备/);
  assert.ok(!active.includes('重置订阅链接'));
  const expired = render({ ...subscription, expires: 1 });
  assert.match(expired, /续费后继续连接/);
  assert.ok(!expired.includes('导入 Clash'));
});
test('account groups subscription, support and security; staff use one management entry', () => {
  const html = renderToStaticMarkup(
    React.createElement(journeys.AccountHub, {
      username: 'Test',
      admin: true,
      s: subscription,
      navigate,
      logout: () => {},
      busy: false,
    }),
  );
  for (const label of ['我的订阅', '支持与帮助', '账号安全', '进入管理'])
    assert.ok(html.includes(label));
});
test('unknown subscription usage is not labelled as usable, and quota bar describes remaining', () => {
  const render = (s) =>
    renderToStaticMarkup(
      React.createElement(journeys.Dashboard, {
        s,
        incidents: [],
        username: 'Test',
        content: null,
        navigate,
        refresh: () => {},
        busy: false,
      }),
    );
  const active = render(subscription);
  assert.match(active, /剩余流量比例/);
  assert.doesNotMatch(active, /已用流量比例/);
  const unknown = render({
    ...subscription,
    used: null,
    enabled: null,
    usage_error: '暂时无法读取',
  });
  assert.match(unknown, /状态待确认/);
  assert.doesNotMatch(unknown, />使用中</);
});
test('support exposes the owner-approved public blog email and Telegram without login', () => {
  const html = renderToStaticMarkup(
    React.createElement(content.Contact, { support: { contact_url: '' } }),
  );
  assert.match(html, /href="mailto:xrcy123@gmail.com"/);
  assert.match(html, /href="https:\/\/t.me\/xrcy97"/);
  const recovery = renderToStaticMarkup(
    React.createElement(features.Recover, { navigate }),
  );
  assert.match(recovery, /href="mailto:xrcy123@gmail.com"/);
  assert.match(recovery, /href="https:\/\/t.me\/xrcy97"/);
});
test('new ticket resumes its in-memory subject and body', () => {
  const html = renderToStaticMarkup(
    React.createElement(features.Tickets, {
      draft: {
        subject: '我的连接问题',
        body: '已填写但尚未提交',
        category: 'connection',
        replies: {},
      },
    }),
  );
  assert.match(html, /我的连接问题/);
  assert.match(html, /已填写但尚未提交/);
});
test('single plan has one compact card and one redemption entry, no assistance sidebar', () => {
  const catalog = {
    plans: [
      {
        id: 'test',
        name: '标准月卡',
        quota_gib: 100,
        days: 30,
        description: '日常使用',
        badge: '月度方案',
        price_label: '',
      },
    ],
    support: { contact_url: '' },
    notices: [],
  };
  const html = renderToStaticMarkup(
    React.createElement(content.PlansPage, {
      content: catalog,
      navigate,
      subscription,
    }),
  );
  assert.equal((html.match(/class="compact-plan"/g) || []).length, 1);
  assert.equal((html.match(/兑换卡密/g) || []).length, 1);
  assert.ok(!html.includes('plans-assistance'));
  assert.ok(!html.includes('plan-cta'));
});
test('device guide exposes three sequential steps and all supported platforms', () => {
  const html = renderToStaticMarkup(
    React.createElement(journeys.DeviceGuide, { navigate, url: null }),
  );
  for (const label of [
    'Windows',
    'macOS',
    'iPhone / iPad',
    'Android',
    'Linux',
    '安装客户端',
    '导入订阅',
    '开启并验证',
  ])
    assert.ok(html.includes(label));
  assert.ok(html.includes('已安装，继续'));
});
test('all added pages render their initial states without browser-only failures', () => {
  for (const name of [
    'Tickets',
    'Sessions',
    'Recover',
    'ServiceStatus',
    'Operations',
    'Redemption',
    'UsagePanel',
  ]) {
    const html = renderToStaticMarkup(
      React.createElement(features[name], {
        navigate,
        onChanged: async () => {},
      }),
    );
    assert.ok(html.length > 40, name);
    assert.ok(!html.includes('undefined'), name);
  }
});
test('subscription link is masked by default and no URL is sent to a QR provider', () => {
  const url = 'https://sub.chuyi.uk/sub/test-private-token-not-real';
  const html = renderToStaticMarkup(
    React.createElement(features.Connection, {
      navigate,
      onChanged: async () => {},
      s: { quota: 100, used: 1, expires: 2000000000, url, pending: false },
    }),
  );
  assert.ok(!html.includes('<code>' + url));
  assert.ok(html.includes('显示链接'));
  assert.ok(html.includes('二维码'));
  assert.ok(!html.includes('api.qrserver'));
});
test('onboarding and expiry warnings match subscription state', () => {
  const render = (s) =>
    renderToStaticMarkup(
      React.createElement(features.GettingStarted, { s, navigate }),
    );
  assert.match(render({ quota: 0, used: 0, expires: 0 }), /三步开始使用/);
  assert.match(
    render({ quota: 100, used: 95, expires: Date.now() / 1000 + 86400 }),
    /剩余流量不足/,
  );
  assert.equal(
    render({ quota: 100, used: 1, expires: Date.now() / 1000 + 86400 * 30 }),
    '',
  );
});
test('QR generation is local and produces a PNG', async () => {
  const value = await QRCode.toDataURL(
    'https://sub.chuyi.uk/sub/fake-test-only',
    { width: 288 },
  );
  assert.ok(value.startsWith('data:image/png;base64,'));
});
