import { useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { api } from './api';
import { FOREVER } from './cycles';

type MailResult = { items: { id: string; recipient: string; account: string; subject: string; status: string; attempts: number; created: number; updated: number; next_attempt: number; provider_id: string; error: string }[]; page: number; pages: number; total: number; available: boolean };
export function MailHistory() {
  const [result, setResult] = useState<{ key: string; data?: MailResult; error?: string } | null>(null);
  const [status, setStatus] = useState('');
  const [page, setPage] = useState(1);
  const [version, setVersion] = useState(0);
  const key = `${page}:${status}:${version}`;
  const data = result?.key === key ? result.data : null;
  const error = result?.key === key ? result.error : '';
  useEffect(() => {
    let active = true;
    void api<MailResult>(`admin/mail-history?page=${page}&status=${status}`).then(data => { if (active) setResult({ key, data }); }).catch(() => { if (active) setResult({ key, error: '邮件记录加载失败，请重试' }); });
    return () => { active = false; };
  }, [page, status, key]);
  const labels: Record<string, string> = { pending: '待发送 / 重试中', sent: '邮件服务已接收', failed: '发送失败', cancelled: '已取消', sending: '提交中 / 结果待确认' };
  return <section className="section" id="admin-mail">
    <h2>邮件通知记录</h2>
    <p className="small muted">包含工单、流量、到期提醒及新增的验证码发送记录。邮件服务接收不代表送达；不保存验证码或邮件正文。旧工单收件地址可能未记录，发送元数据保留 90 天。</p>
    <div className="actions">
      <select aria-label="邮件状态" value={status} onChange={e => { setStatus(e.target.value); setPage(1); }}><option value="">全部状态</option>{Object.entries(labels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
      <Button variant="outline" onClick={() => setVersion(v => v + 1)}>刷新邮件记录</Button>
    </div>
    {error && <p role="alert">{error}</p>}
    {!data && !error && <output>正在加载邮件记录…</output>}
    {data && <>
      {!data.available && <p className="message error">邮件服务尚未配置</p>}
      <p className="small muted">共 {data.total} 条</p>
      {data.items.map(item => <article className="surface" key={item.id}>
        <strong>{item.subject} · {labels[item.status] || item.status}</strong>
        <p>{item.recipient || '历史记录未保存收件地址'}</p>
        {item.account && <p className="small muted">所属账号：{item.account}</p>}
        <p className="small muted">创建：{new Date(item.created * 1000).toLocaleString()} · 尝试 {item.attempts} 次{item.updated > 0 && ` · 最近提交：${new Date(item.updated * 1000).toLocaleString()}`}</p>
        {item.status === 'pending' && item.next_attempt > 0 && <p className="small muted">下次尝试不早于：{new Date(item.next_attempt * 1000).toLocaleString()}</p>}
        {item.error && <p>{item.error}</p>}
        {item.provider_id && <p className="small muted">服务商邮件编号：{item.provider_id}</p>}
      </article>)}
      {!data.items.length && <p className="empty muted">暂无邮件记录</p>}
      <div className="actions"><Button disabled={page <= 1} onClick={() => setPage(p => p - 1)}>上一页</Button><span>{page} / {data.pages}</span><Button disabled={page >= data.pages} onClick={() => setPage(p => p + 1)}>下一页</Button></div>
    </>}
  </section>;
}
type Diagnosis = {
  username: string;
  account: { id: string; disabled: number; must_change: number } | null;
  events: { outcome: string; created: number }[];
  limited_until: number | null;
  note: string;
};
const date = (n: number) => n >= FOREVER ? '不限期' : new Date(n * 1000).toLocaleString('zh-CN');
const outcomes: Record<string, string> = {
  unknown_user: '账号不存在',
  wrong_password: '密码不正确',
  disabled: '账号已停用',
  rate_limited: '触发登录频率限制',
  success: '密码验证通过',
};

export function LoginDiagnosis() {
  const [username, setUsername] = useState(''),
    [data, setData] = useState<Diagnosis | null>(null),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false);
  const sequence = useRef(0);
  useEffect(
    () => () => {
      sequence.current++;
    },
    [],
  );
  return (
    <section className="section">
      <h2>登录问题诊断</h2>
      <p className="small muted">
        核对用户名与近期登录结果，不查看或保存用户密码。
      </p>
      <form
        className="support-search"
        onSubmit={(e) => {
          e.preventDefault();
          const request = ++sequence.current;
          setBusy(true);
          setError('');
          setData(null);
          void api<Diagnosis>('admin/login-diagnosis', { username })
            .then((r) => {
              if (request === sequence.current) setData(r);
            })
            .catch((e) => {
              if (request === sequence.current) setError(e.message);
            })
            .finally(() => {
              if (request === sequence.current) setBusy(false);
            });
        }}
      >
        <Input
          aria-label="待诊断用户名"
          placeholder="完整邮箱或原用户名"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          maxLength={254}
          required
        />
        <Button disabled={busy}>检查登录</Button>
      </form>
      {error && (
        <p className="message error" role="alert">
          {error}
        </p>
      )}
      {data && (
        <div aria-live="polite">
          <p>
            <strong>{data.username}</strong> ·{' '}
            {!data.account
              ? '账号不存在'
              : data.account.disabled
                ? '账号已停用'
                : data.account.must_change
                  ? '账号正常，需修改临时密码'
                  : '账号正常'}
          </p>
          {data.account && (
            <a
              className="text-link"
              href={'#/admin_users?user=' + encodeURIComponent(data.account.id)}
            >
              打开用户详情 →
            </a>
          )}
          {data.limited_until && (
            <p className="message error">
              用户名限流至 {date(data.limited_until)}
            </p>
          )}
          <p className="small muted">{data.note}</p>
          {data.events.length ? (
            data.events.map((e, i) => (
              <div className="history-row" key={i}>
                <span>{outcomes[e.outcome] || '其他结果'}</span>
                <time>{date(e.created)}</time>
              </div>
            ))
          ) : (
            <p className="empty">
              暂无可查询的登录记录，不代表用户从未尝试登录。
            </p>
          )}
        </div>
      )}
    </section>
  );
}

type Readiness = {
  connectivity: {
    checked_at: number;
    subscription_ok: boolean;
    nodes: { name: string; ok: boolean; latency_ms: number | null }[];
  } | null;
  alerts: { level: string; title: string; detail: string }[];
  backup: { verified_at: number; restore_verified: boolean } | null;
  external_notifications: boolean;
  offsite_backup: boolean;
};
export function OperationsReadiness() {
  const [data, setData] = useState<Readiness | null>(null),
    [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    const refresh = () => {
      if (document.hidden) return;
      void api<Readiness>('admin/readiness')
        .then((x) => {
          if (active) {
            setData(x);
            setError('');
          }
        })
        .catch((e) => {
          if (active) setError(e.message);
        });
    };
    refresh();
    const timer = setInterval(refresh, 60000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, []);
  return (
    <section className="section">
      <h2>服务检查与告警</h2>
      {error && <p className="message error">{error}</p>}
      {data && (
        <>
          {data.alerts.length ? (
            data.alerts.map((a, i) => (
              <div
                className={'message ' + (a.level === 'error' ? 'error' : '')}
                key={i}
              >
                <strong>{a.title}</strong>
                <span>{a.detail}</span>
              </div>
            ))
          ) : (
            <p className="muted">当前没有触发预算、同步或备份告警。</p>
          )}
          <p className="small muted">
            实际连接探测：
            {data.connectivity
              ? date(data.connectivity.checked_at)
              : '尚未完成'}{' '}
            · 从监控服务器经 HY2
            节点访问测试站点，不代表所有地区用户的线路质量。
          </p>
          {data.connectivity?.nodes.map((n) => (
            <p className="small" key={n.name}>
              {n.name} · {n.ok ? '代理请求成功' : '代理请求未成功'}
              {n.latency_ms !== null ? ` · ${n.latency_ms} ms` : ''}
            </p>
          ))}
          <p className="small muted">
            恢复演练：
            {data.backup?.restore_verified
              ? date(data.backup.verified_at) + ' 已通过'
              : '待验证'}{' '}
            · 隔离副本验证，不覆盖线上库。
          </p>
          <p className="small muted">
            站外通知：
            {data.external_notifications ? '已配置' : '待指定接收渠道'} ·
            异机备份：{data.offsite_backup ? '已配置' : '待指定备份位置'}
          </p>
        </>
      )}
    </section>
  );
}
