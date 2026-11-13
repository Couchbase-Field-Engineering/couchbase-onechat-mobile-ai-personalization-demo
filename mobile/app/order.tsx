import { Ionicons } from '@expo/vector-icons';
import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { useData } from '@/src/data/DataContext';
import { theme } from '@/src/theme';
import { Button, Card, Empty, fmtDate, money, Pill, SectionTitle } from '@/src/ui/components';
import { ChoiceRow } from '@/src/ui/Choice';
import { addDays, short } from '@/src/ui/dates';
import { form, OFFLINE_NOTE } from '@/src/ui/form';
import { RequestTracker } from '@/src/ui/RequestTracker';

const STEPS = ['processing', 'shipped', 'out_for_delivery', 'delivered'];
const STEP_LABEL: Record<string, string> = { processing: 'Processing', shipped: 'Shipped', out_for_delivery: 'Out for delivery', delivered: 'Delivered' };

/** Order tracking, straight from the profile document in Couchbase Lite. */
export default function OrderScreen() {
  const params = useLocalSearchParams<{ order_id?: string; reschedule?: string }>();
  const { snap, request } = useData();
  const p = snap.profile;
  const orders = p?.orders ?? [];
  const o = orders.find((x) => x.order_id === params.order_id) ?? orders.find((x) => ['processing', 'shipped', 'out_for_delivery'].includes(x.status)) ?? orders[0];
  const [day, setDay] = useState<string | undefined>();
  const [win, setWin] = useState<string | undefined>(o?.delivery_window ?? undefined);
  const [reqId, setReqId] = useState<string | null>(null);
  if (!p || !o) return <Empty icon="cube-outline" title="No orders" body="Orders you place appear here with live tracking." />;

  const today = p.export_date;
  const at = STEPS.indexOf(o.status);
  const canMove = ['processing', 'shipped'].includes(o.status) && o.carrier === 'Larkfield Delivery' && !!o.eta;
  const days = canMove ? Array.from({ length: 8 }, (_, i) => addDays(o.eta!, i)).filter((d) => d > today && d !== o.eta) : [];
  const returnable = o.status === 'delivered';

  const submit = async () => {
    if (!day) return;
    const req = await request('reschedule_delivery', { order_id: o.order_id, date: day, window: win ?? o.delivery_window ?? '' }, `Move delivery · ${o.order_id} to ${short(day)}`);
    setReqId(req._id);
  };

  return (
    <ScrollView contentContainerStyle={form.body}>
      <Card style={{ padding: 16, gap: 6 }}>
        <View style={form.rowBetween}>
          <Text style={form.meta}>ORDER {o.order_id}</Text>
          <Pill label={o.status.replace(/_/g, ' ')} tone={o.status === 'delivered' ? 'ok' : o.status === 'cancelled' ? 'neutral' : 'orange'} />
        </View>
        <Text style={form.h2}>
          {o.status === 'delivered' ? `Delivered ${fmtDate(o.delivered_at)}` : o.status === 'cancelled' ? 'Cancelled' : `Arriving ${fmtDate(o.eta, { weekday: 'long', month: 'long', day: 'numeric' })}`}
        </Text>
        <Text style={form.meta}>
          {o.carrier}{o.delivery_window && o.status !== 'delivered' ? ` · ${o.delivery_window}` : ''}{o.tracking_number ? ` · ${o.tracking_number}` : ''}
        </Text>
        {o.status !== 'cancelled' ? (
          <View style={styles.track}>
            {STEPS.map((s, i) => (
              <View key={s} style={{ flex: 1, alignItems: 'center', gap: 4 }}>
                <View style={[styles.node, i <= at && { backgroundColor: theme.color.red, borderColor: theme.color.red }]}>
                  {i <= at ? <Ionicons name="checkmark" size={12} color={theme.color.onDark} /> : null}
                </View>
                <Text style={[styles.nodeText, i <= at && { color: theme.color.ink, fontWeight: '700' }]}>{STEP_LABEL[s]}</Text>
              </View>
            ))}
          </View>
        ) : null}
      </Card>

      <SectionTitle title="Items" />
      <Card style={{ padding: 16, gap: 8 }}>
        {o.items.map((i) => (
          <View key={i.sku} style={form.rowBetween}>
            <Text style={{ fontWeight: '700', color: theme.color.text, flex: 1 }}>{i.name}</Text>
            <Text style={form.meta}>{money(i.price)}</Text>
          </View>
        ))}
        <View style={[form.rowBetween, { borderTopWidth: 1, borderTopColor: theme.color.border, paddingTop: 8 }]}>
          <Text style={form.meta}>Total{o.offer_code ? ` · ${o.offer_code} applied` : ''}</Text>
          <Text style={{ fontWeight: '700', color: theme.color.text }}>{money(o.total_usd)}</Text>
        </View>
        {returnable ? (
          <View style={{ alignItems: 'flex-start', marginTop: 4 }}>
            <Button small kind="ghost" label="Return or exchange" icon="return-down-back" onPress={() => router.push({ pathname: '/return', params: { order_id: o.order_id } })} />
          </View>
        ) : null}
      </Card>

      <SectionTitle title="Tracking" />
      <Card style={{ padding: 16, gap: 10 }}>
        {[...o.events].reverse().map((e, i) => (
          <View key={i} style={{ flexDirection: 'row', gap: 10 }}>
            <Ionicons name={i === 0 ? 'radio-button-on' : 'ellipse-outline'} size={14} color={i === 0 ? theme.color.red : theme.color.faint} style={{ marginTop: 3 }} />
            <View style={{ flex: 1 }}>
              <Text style={{ color: theme.color.text, fontWeight: i === 0 ? '700' : '400' }}>{e.text}</Text>
              <Text style={form.meta}>{fmtDate(e.at)}</Text>
            </View>
          </View>
        ))}
      </Card>

      {reqId ? <RequestTracker id={reqId} onRetry={() => setReqId(null)} /> : canMove ? (
        <>
          <SectionTitle title={params.reschedule ? 'Pick a new delivery day' : 'Need a different day?'} />
          <ChoiceRow options={days.map((d) => ({ value: d, label: short(d) }))} value={day} onChange={setDay} />
          <View style={{ height: 8 }} />
          <ChoiceRow options={(snap.catalog?.delivery_windows ?? ['8am-12pm', '12pm-4pm', '4pm-8pm']).map((w) => ({ value: w, label: w }))} value={win} onChange={setWin} />
          <View style={{ marginTop: 14 }}>
            <Button label={day ? `Move delivery to ${short(day)}` : 'Choose a day'} icon="calendar" disabled={!day} onPress={() => void submit()} />
          </View>
          <Text style={form.tiny}>{OFFLINE_NOTE}</Text>
        </>
      ) : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  track: { flexDirection: 'row', marginTop: 14 },
  node: { width: 22, height: 22, borderRadius: 11, borderWidth: 2, borderColor: theme.color.border, alignItems: 'center', justifyContent: 'center', backgroundColor: theme.color.surface },
  nodeText: { fontSize: 10, color: theme.color.faint, textAlign: 'center' },
});
