import { useState } from 'react';
import { ScrollView, Text, TextInput, View } from 'react-native';
import { useData } from '@/src/data/DataContext';
import { theme } from '@/src/theme';
import { Button, Card, Empty, fmtDate, Pill, SectionTitle } from '@/src/ui/components';
import { ChoiceRow } from '@/src/ui/Choice';
import { short, weekdaysAfter, workingDays } from '@/src/ui/dates';
import { form, OFFLINE_NOTE } from '@/src/ui/form';
import { RequestTracker } from '@/src/ui/RequestTracker';

export default function TimeOff() {
  const { snap, request } = useData();
  const p = snap.profile;
  const [start, setStart] = useState<string | undefined>();
  const [end, setEnd] = useState<string | undefined>();
  const [note, setNote] = useState('');
  const [reqId, setReqId] = useState<string | null>(null);
  if (!p) return null;
  if (p.audience !== 'employee' || !p.hr) {
    return <Empty icon="lock-closed-outline" title="Team members only" body="Time off is part of the Larkfield team workspace." />;
  }
  const pto = p.hr.pto;
  const days = weekdaysAfter(p.export_date, 20);
  const last = end && start && end >= start ? end : start;
  const n = start && last ? workingDays(start, last) : 0;
  const over = n > pto.balance_days;

  const submit = async () => {
    if (!start || !last) return;
    const req = await request('request_time_off', { start_date: start, end_date: last, note: note.trim() }, `Time off · ${short(start)}${last !== start ? ` to ${short(last)}` : ''}`);
    setReqId(req._id);
  };

  return (
    <ScrollView contentContainerStyle={form.body} keyboardShouldPersistTaps="handled">
      <Card style={{ padding: 16, gap: 6 }}>
        <Text style={form.meta}>PAID TIME OFF</Text>
        <Text style={form.big}>{pto.balance_days} days</Text>
        <Text style={[form.meta, { textAlign: 'center' }]}>Accruing {pto.accrual_per_month ?? 1.5} days a month · {pto.used_days} used · approved by {p.employment?.manager}</Text>
      </Card>
      {pto.requests.length ? (
        <>
          <SectionTitle title="Already requested" />
          {pto.requests.map((r) => (
            <Card key={r.start_date} style={[form.opt, { borderWidth: 0 }]}>
              <Text style={{ flex: 1, fontWeight: '700', color: theme.color.text }}>{fmtDate(r.start_date)}{r.end_date !== r.start_date ? ` - ${fmtDate(r.end_date)}` : ''} · {r.days} day{r.days !== 1 ? 's' : ''}</Text>
              <Pill label={r.status.replace(/_/g, ' ')} tone="orange" />
            </Card>
          ))}
        </>
      ) : null}
      {reqId ? <RequestTracker id={reqId} onRetry={() => setReqId(null)} /> : (
        <>
          <SectionTitle title="First day off" />
          <ChoiceRow options={days.map((d) => ({ value: d, label: short(d) }))} value={start} onChange={(d) => { setStart(d); if (end && end < d) setEnd(undefined); }} />
          <SectionTitle title="Last day off" />
          <ChoiceRow options={days.filter((d) => !start || d >= start).map((d) => ({ value: d, label: short(d) }))} value={last} onChange={setEnd} />
          <SectionTitle title="Note for your manager (optional)" />
          <TextInput value={note} onChangeText={setNote} placeholder="e.g. Family visit" placeholderTextColor={theme.color.faint} style={form.input} />
          {n ? <Text style={[form.meta, { marginTop: 10, color: over ? theme.color.danger : theme.color.muted }]}>{n} working day{n !== 1 ? 's' : ''}{over ? ` - more than your ${pto.balance_days}-day balance` : ` · ${pto.balance_days - n} left after this`}</Text> : null}
          <View style={{ marginTop: 16 }}>
            <Button label={n ? `Request ${n} day${n !== 1 ? 's' : ''} off` : 'Choose your dates'} icon="sunny" disabled={!n || over} onPress={() => void submit()} />
          </View>
          <Text style={form.tiny}>{OFFLINE_NOTE}</Text>
        </>
      )}
    </ScrollView>
  );
}
