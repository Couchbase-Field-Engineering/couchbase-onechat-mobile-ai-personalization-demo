import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Pressable, ScrollView, Text, View } from 'react-native';
import { useData } from '@/src/data/DataContext';
import { theme } from '@/src/theme';
import type { ReturnOption } from '@/src/types';
import { Button, Card, Empty, fmtDate, money, Pill, SectionTitle } from '@/src/ui/components';
import { ChoiceRow } from '@/src/ui/Choice';
import { form, OFFLINE_NOTE } from '@/src/ui/form';
import { RequestTracker } from '@/src/ui/RequestTracker';

/**
 * Returns and exchanges. The options come from the For You feed's return card
 * (or the cached return context), so the whole flow works offline. Confirm
 * creates a `start_return` request, which the Returns Agent runs through Couchbase Labs Agent Operations Manager.
 */
export default function ReturnScreen() {
  const params = useLocalSearchParams<{ order_id?: string; sku?: string; resolution?: string; exchange_sku?: string }>();
  const { snap, request } = useData();
  const card = snap.feed?.cards.find((c) => c.kind === 'return');
  const fromCtx = ((snap.contexts.return?.facts?.data?.items ?? []) as (ReturnOption & { eligible: boolean })[]).filter((i) => i.eligible);
  const all: ReturnOption[] = card?.options ?? fromCtx;
  const options = params.order_id && !params.sku ? all.filter((o) => o.order_id === params.order_id) : all;
  const initial = options.find((o) => o.sku === params.sku && (!params.order_id || o.order_id === params.order_id)) ?? (options.length === 1 ? options[0] : undefined);
  const [key, setKey] = useState(initial ? `${initial.order_id}/${initial.sku}` : undefined);
  const sel = options.find((o) => `${o.order_id}/${o.sku}` === key);
  const [reason, setReason] = useState<string | undefined>();
  const [mode, setMode] = useState<'refund' | 'exchange'>(params.resolution === 'exchange' ? 'exchange' : 'refund');
  const [ex, setEx] = useState<string | undefined>(params.exchange_sku);
  const [reqId, setReqId] = useState<string | null>(null);
  const reasons = card?.reasons ?? snap.catalog?.return_reasons ?? ['Changed my mind', 'Wrong size or fit', 'Arrived damaged'];

  if (!snap.profile) return null;
  if (!options.length) return <Empty icon="return-down-back-outline" title="Nothing to return" body="Items you've received appear here while they're inside your return window." />;
  const exSel = sel?.exchange_options.find((x) => x.sku === ex);
  const ready = !!sel && !!reason && (mode === 'refund' || !!exSel);

  const submit = async () => {
    if (!sel || !reason) return;
    const args: Record<string, unknown> = { order_id: sel.order_id, sku: sel.sku, reason, resolution: mode };
    if (mode === 'exchange' && exSel) args.exchange_sku = exSel.sku;
    const req = await request('start_return', args, mode === 'exchange' ? `Exchange ${sel.name} for ${exSel?.name}` : `Return ${sel.name} · ${money(sel.price)} back`);
    setReqId(req._id);
  };

  return (
    <ScrollView contentContainerStyle={form.body}>
      {reqId ? <RequestTracker id={reqId} onRetry={() => setReqId(null)} /> : (
        <>
          <SectionTitle title="What's going back?" />
          {options.map((o) => {
            const k = `${o.order_id}/${o.sku}`;
            return (
              <Pressable key={k} onPress={() => { setKey(k); setEx(undefined); }}>
                <Card style={[form.opt, key === k && form.optSel]}>
                  <View style={{ flex: 1, gap: 4 }}>
                    <Text style={form.h3}>{o.name}</Text>
                    <Text style={form.meta}>Order {o.order_id} · delivered {fmtDate(o.delivered_at)} · {money(o.price)}</Text>
                    <Pill label={`${o.days_left} days left of ${o.window_days}`} tone={o.days_left <= 7 ? 'red' : 'ok'} icon="time-outline" />
                  </View>
                  <Ionicons name={key === k ? 'radio-button-on' : 'radio-button-off'} size={22} color={theme.color.ink} />
                </Card>
              </Pressable>
            );
          })}

          {sel ? (
            <>
              <SectionTitle title="Why?" />
              <ChoiceRow options={reasons.map((r) => ({ value: r, label: r }))} value={reason} onChange={setReason} />

              <View style={form.seg}>
                {(['refund', 'exchange'] as const).map((m) => (
                  <Pressable key={m} onPress={() => setMode(m)} style={[form.segBtn, mode === m && form.segOn]}>
                    <Text style={[form.segText, mode === m && { color: theme.color.onDark }]}>{m === 'refund' ? `Refund ${money(sel.price)}` : 'Exchange'}</Text>
                  </Pressable>
                ))}
              </View>

              {mode === 'exchange' ? (
                sel.exchange_options.map((x) => (
                  <Pressable key={x.sku} onPress={() => setEx(x.sku)} disabled={x.in_stock <= 0}>
                    <Card style={[form.opt, ex === x.sku && form.optSel, x.in_stock <= 0 && { opacity: 0.45 }]}>
                      <View style={{ flex: 1, gap: 4 }}>
                        <Text style={{ fontWeight: '700', color: theme.color.text }}>{x.name}</Text>
                        <Text style={form.meta}>
                          {x.price === sel.price ? 'Even exchange' : x.price > sel.price ? `${money(x.price - sel.price)} more` : `${money(sel.price - x.price)} back to your card`}
                        </Text>
                      </View>
                      <Pill label={x.in_stock > 0 ? (x.in_stock <= 3 ? `Only ${x.in_stock} left` : 'In stock') : 'Out of stock'} tone={x.in_stock <= 3 ? 'warn' : 'neutral'} />
                    </Card>
                  </Pressable>
                ))
              ) : (
                <Card style={{ padding: 16, gap: 6 }}>
                  <Text style={form.meta}>Drop it at any Larkfield store or UPS location with your return code. {money(sel.price)} goes back to your card within 3 business days of the scan.</Text>
                </Card>
              )}

              <View style={{ marginTop: 14 }}>
                <Button label={mode === 'exchange' ? 'Confirm exchange' : 'Confirm return'} icon="checkmark" disabled={!ready} onPress={() => void submit()} />
              </View>
              <Text style={form.tiny}>Confirm hands this to the Returns Agent through Couchbase Labs Agent Operations Manager. {OFFLINE_NOTE}</Text>
            </>
          ) : null}
        </>
      )}
    </ScrollView>
  );
}
