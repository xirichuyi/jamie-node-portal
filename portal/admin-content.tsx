import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { useEffect, useState, type ReactNode } from 'react';
import { api } from './api';
import { TermsFields, ruleLabel } from './cycles';

import type { Catalog, Notice, Plan, Support } from './content';

const categoryLabel: Record<string, string> = {
  info: '使用须知',
  maintenance: '维护通知',
  update: '服务更新',
};
function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
  );
}
const blankPlan = {
  id: '',
  name: '',
  description: '',
  quota_gib: 100,
  days: 30,
  price_label: '',
  usdt_price: '',
  badge: '',
  published: 0,
  sort_order: 0,
  revision: 1,
};
const blankNotice = {
  id: '',
  title: '',
  body: '',
  category: 'info',
  published: 0,
  pinned: 0,
  created: 0,
  updated: 0,
  revision: 1,
};
export function ContentAdmin({ onSaved }: { onSaved: () => Promise<void> }) {
  const [data, setData] = useState<Catalog | null>(null),
    [plan, setPlan] = useState<Plan>(blankPlan),
    [notice, setNotice] = useState<Notice>(blankNotice),
    [support, setSupport] = useState<Support | null>(null),
    [busy, setBusy] = useState(false),
    [message, setMessage] = useState(''),
    [error, setError] = useState('');
  async function load() {
    const d = await api<Catalog>('admin/content');
    setData(d);
    setSupport(d.support);
    return d;
  }
  useEffect(() => {
    void load().catch((e) => setError(e.message));
  }, []);
  async function save(kind: string, value: unknown) {
    setBusy(true);
    setError('');
    setMessage('');
    try {
      await api('admin/' + kind, value);
      const d = await load();
      if (kind === 'plan') setPlan(blankPlan);
      if (kind === 'notice') setNotice(blankNotice);
      await onSaved();
      setMessage(
        kind === 'notice'
          ? (value as Notice).published
            ? '公告已发布，用户进入网站即可看到；已打开的页面会在一分钟内更新。'
            : '公告已保存为草稿，不会在用户端展示。'
          : '已保存，前台内容已更新。',
      );
      return d;
    } catch (e) {
      setError(e instanceof Error ? e.message : '保存失败');
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="section cms">
      {error && (
        <p className="message error" role="alert">
          {error}
        </p>
      )}
      {message && (
        <p className="message" role="status">
          {message}
        </p>
      )}
      <Tabs defaultValue="notices">
        <TabsList>
          <TabsTrigger value="plans">套餐管理</TabsTrigger>
          <TabsTrigger value="notices">公告管理</TabsTrigger>
          <TabsTrigger value="support">联系设置</TabsTrigger>
        </TabsList>
        <TabsContent value="plans">
          <div className="cms-list">
            {data?.plans.map((p) => (
              <div key={p.id}>
                <span>
                  <strong>{p.name}</strong>
                  <small>
                    {p.quota_gib} GiB · {ruleLabel(p)} ·{' '}
                    {p.published ? '已上架' : '草稿 / 已下架'}
                  </small>
                </span>
                <Button
                  variant="outline"
                  onClick={() => {
                    setPlan({ ...p, usdt_price: p.usdt_micros ? String(p.usdt_micros / 1000000) : '' });
                    setMessage('');
                  }}
                >
                  编辑
                </Button>
              </div>
            ))}
          </div>
          <form
            className="surface"
            onSubmit={(e) => {
              e.preventDefault();
              void save('plan', { ...plan, published: !!plan.published });
            }}
          >
            <div className="section-heading">
              <h2>{plan.id ? '编辑套餐' : '新建套餐'}</h2>
              {plan.id && (
                <Button variant="ghost" onClick={() => setPlan(blankPlan)}>
                  取消编辑
                </Button>
              )}
            </div>
            <div className="form-grid">
              <Field label="套餐名称">
                <Input
                  required
                  maxLength={60}
                  value={plan.name}
                  onChange={(e) => setPlan({ ...plan, name: e.target.value })}
                />
              </Field>
              <Field label="价格说明（选填）">
                <Input
                  maxLength={40}
                  placeholder="例如 ¥20 / 张，不填写则显示联系管理员"
                  value={plan.price_label}
                  onChange={(e) =>
                    setPlan({ ...plan, price_label: e.target.value })
                  }
                />
              </Field>
              <Field label="USDT 在线售价（留空关闭购买）">
                <Input type="text" inputMode="decimal" placeholder="例如 3" value={plan.usdt_price || ''} onChange={e => setPlan({ ...plan, usdt_price: e.target.value })} />
              </Field>
              <TermsFields value={plan} onChange={(patch) => setPlan({ ...plan, ...patch })} />
              <Field label="标签（选填）">
                <Input
                  maxLength={20}
                  value={plan.badge}
                  onChange={(e) => setPlan({ ...plan, badge: e.target.value })}
                />
              </Field>
              <Field label="排序（小的在前）">
                <Input
                  type="number"
                  required
                  min={0}
                  max={999}
                  value={plan.sort_order}
                  onChange={(e) =>
                    setPlan({ ...plan, sort_order: Number(e.target.value) })
                  }
                />
              </Field>
            </div>
            <Field label="套餐说明">
              <Textarea
                maxLength={500}
                value={plan.description}
                onChange={(e) =>
                  setPlan({ ...plan, description: e.target.value })
                }
              />
            </Field>
            <label className="check-line">
              <Checkbox
                checked={!!plan.published}
                onCheckedChange={(v) =>
                  setPlan({ ...plan, published: v ? 1 : 0 })
                }
              />
              上架，在前台展示
            </label>
            <p className="small muted">
              取消上架后保存即可下架。修改套餐不影响已发出的卡密。
            </p>
            <Button type="submit" disabled={busy}>
              保存套餐
            </Button>
          </form>
        </TabsContent>
        <TabsContent value="notices">
          <div className="cms-list">
            {data?.notices.map((n) => (
              <div key={n.id}>
                <span>
                  <strong>{n.title}</strong>
                  <small>
                    {categoryLabel[n.category]} ·{' '}
                    {n.published ? '已发布' : '草稿'}
                    {n.pinned ? ' · 置顶' : ''}
                  </small>
                </span>
                <Button
                  variant="outline"
                  onClick={() => {
                    setNotice({ ...n });
                    setMessage('');
                  }}
                >
                  编辑
                </Button>
              </div>
            ))}
          </div>
          <form
            className="surface"
            onSubmit={(e) => {
              e.preventDefault();
              void save('notice', {
                ...notice,
                published: !!notice.published,
                pinned: !!notice.pinned,
              });
            }}
          >
            <div className="section-heading">
              <h2>{notice.id ? '编辑公告' : '新建公告'}</h2>
              {notice.id && (
                <Button variant="ghost" onClick={() => setNotice(blankNotice)}>
                  取消编辑
                </Button>
              )}
            </div>
            <Field label="标题">
              <Input
                required
                maxLength={120}
                value={notice.title}
                onChange={(e) =>
                  setNotice({ ...notice, title: e.target.value })
                }
              />
            </Field>
            <div className="field">
              <span id="notice-kind">公告类型</span>
              <Select
                value={notice.category}
                onValueChange={(v) =>
                  setNotice({ ...notice, category: String(v) })
                }
              >
                <SelectTrigger aria-labelledby="notice-kind">
                  <SelectValue>{categoryLabel[notice.category]}</SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {Object.entries(categoryLabel).map(([key, label]) => (
                    <SelectItem key={key} value={key}>
                      {label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <Field label="正文（纯文本）">
              <Textarea
                required
                rows={6}
                maxLength={4000}
                value={notice.body}
                onChange={(e) => setNotice({ ...notice, body: e.target.value })}
              />
            </Field>
            <div className="actions">
              <label className="check-line">
                <Checkbox
                  checked={!!notice.published}
                  onCheckedChange={(v) =>
                    setNotice({ ...notice, published: v ? 1 : 0 })
                  }
                />
                发布到前台
              </label>
              <label className="check-line">
                <Checkbox
                  checked={!!notice.pinned}
                  onCheckedChange={(v) =>
                    setNotice({ ...notice, pinned: v ? 1 : 0 })
                  }
                />
                置顶并在首次进入时提醒
              </label>
            </div>
            <Button type="submit" disabled={busy}>
              保存公告
            </Button>
          </form>
        </TabsContent>
        <TabsContent value="support">
          {support && (
            <form
              className="surface"
              onSubmit={(e) => {
                e.preventDefault();
                void save('support', support);
              }}
            >
              <Field label="联系按钮文字">
                <Input
                  required
                  maxLength={40}
                  value={support.contact_label}
                  onChange={(e) =>
                    setSupport({ ...support, contact_label: e.target.value })
                  }
                />
              </Field>
              <Field label="客服链接（选填）">
                <Input
                  maxLength={400}
                  placeholder="https://t.me/你的用户名 或 mailto:邮箱"
                  value={support.contact_url}
                  onChange={(e) =>
                    setSupport({ ...support, contact_url: e.target.value })
                  }
                />
              </Field>
              <Field label="联系说明">
                <Textarea
                  maxLength={1000}
                  value={support.contact_note}
                  onChange={(e) =>
                    setSupport({ ...support, contact_note: e.target.value })
                  }
                />
              </Field>
              <p className="small muted">
                仅支持 HTTPS 或
                mailto:邮箱。留空时显示联系说明，不生成无效按钮。
              </p>
              <Button type="submit" disabled={busy}>
                保存联系方式
              </Button>
            </form>
          )}
        </TabsContent>
      </Tabs>
    </section>
  );
}
