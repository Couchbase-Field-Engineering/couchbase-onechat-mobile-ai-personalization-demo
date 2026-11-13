import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Pressable, ScrollView, Text, TextInput, View } from 'react-native';
import { useData } from '@/src/data/DataContext';
import { theme } from '@/src/theme';
import type { SlotDay } from '@/src/types';
import { Button, Card, Empty, fmtDate, Pill, SectionTitle } from '@/src/ui/components';
import { ChoiceRow } from '@/src/ui/Choice';
import { short } from '@/src/ui/dates';
import { form, OFFLINE_NOTE } from '@/src/ui/form';
import { RequestTracker } from '@/src/ui/RequestTracker';

/**
 * Lead capture and consultation booking. Two steps a prospect can take in
 * either order: share headcount / budget / timeline (qualifies the lead and
 * assigns a specialist), and pick a consultation slot. Open slots come from
 * the feed's consult card, so the screen works offline.
 */
export default function Consult() {
  const params = useLocalSearchParams<{ step?: string }>();
  const { snap, request } = useData();
  const p = snap.profile;
  const cat = snap.catalog;
  const card = snap.feed?.cards.find((c) => c.kind === 'consult');
  const days: SlotDay[] = card?.slots ?? ((snap.contexts.sales?.facts?.data?.days ?? []) as SlotDay[]);
  const isLead = p?.audience === 'lead';
  const [step, setStep] = useState<'details' | 'book'>(params.step === 'details' && isLead ? 'details' : 'book');
  const [seats, setSeats] = useState(String(p?.lead?.seats ?? p?.company?.employees ?? 10));
  const [budget, setBudget] = useState<string | undefined>(p?.lead?.budget_band ?? undefined);
  const [timeline, setTimeline] = useState<string | undefined>(p?.lead?.timeline ?? undefined);
  const [phone, setPhone] = useState(p?.phone ?? '');
  const [topic, setTopic] = useState<string | undefined>(p?.lead?.interest?.[0] ?? cat?.consult_topics?.[0]);
  const [date, setDate] = useState<string | undefined>(days.find((d) => d.slots.some((s) => s.open > 0))?.date);
  const [time, setTime] = useState<string | undefined>();
  const [channel, setChannel] = useState('video');
  const [reqId, setReqId] = useState<string | null>(null);
  if (!p || !cat) return null;
  const booked = p.consultation;
  const n = Math.max(1, Math.min(5000, parseInt(seats, 10) || 0));
  const bundle = cat.bundles.find((b) => n >= b.seats[0] && n <= b.seats[1]) ?? cat.bundles[cat.bundles.length - 1];
  const slots = days.find((d) => d.date === date)?.slots ?? [];

  const sendDetails = async () => {
    if (!budget || !timeline) return;
    const req = await request('submit_lead_details', { seats: n, budget_band: budget, timeline, phone, interest: topic ?? '' }, `Details shared · ${n} seats · ${budget}`);
    setReqId(req._id);
  };
  const book = async () => {
    if (!date || !time) return;
    const req = await request('book_consultation', { date, time, topic: topic ?? '', channel }, `Consultation · ${short(date)} at ${time}`);
    setReqId(req._id);
  };

  return (
    <ScrollView contentContainerStyle={form.body} keyboardShouldPersistTaps="handled">
      {isLead ? (
        <Card style={{ padding: 16, gap: 4 }}>
          <Text style={form.meta}>{cat.company.business_brand.toUpperCase()}</Text>
          <Text style={form.h2}>{p.company?.name}</Text>
          <Text style={form.meta}>{p.company?.industry} · {p.company?.employees} people · {p.company?.city}</Text>
          <View style={{ flexDirection: 'row', gap: 6, flexWrap: 'wrap', marginTop: 6 }}>
            <Pill label={`Lead: ${String(p.lead?.status).replace(/_/g, ' ')}`} tone={p.lead?.status === 'new' ? 'neutral' : 'ok'} />
            {p.lead?.owner ? <Pill label={`Specialist: ${p.lead.owner}`} tone="ink" icon="person" /> : null}
          </View>
        </Card>
      ) : null}

      {reqId ? (
        <RequestTracker id={reqId} onRetry={() => setReqId(null)} />
      ) : (
        <>
          {isLead ? (
            <View style={form.seg}>
              {(['details', 'book'] as const).map((s) => (
                <Pressable key={s} onPress={() => setStep(s)} style={[form.segBtn, step === s && form.segOn]}>
                  <Text style={[form.segText, step === s && { color: theme.color.onDark }]}>{s === 'details' ? 'Your details' : 'Book a time'}</Text>
                </Pressable>
              ))}
            </View>
          ) : null}

          {step === 'details' ? (
            <>
              <SectionTitle title="How many seats?" />
              <Card style={{ padding: 16, gap: 10 }}>
                <View style={form.stepper}>
                  <Pressable onPress={() => setSeats(String(Math.max(1, n - (n > 50 ? 10 : 1))))} style={form.step}><Ionicons name="remove" size={22} color={theme.color.ink} /></Pressable>
                  <TextInput value={seats} onChangeText={setSeats} keyboardType="number-pad" style={[form.big, { minWidth: 110 }]} />
                  <Pressable onPress={() => setSeats(String(n + (n >= 50 ? 10 : 1)))} style={form.step}><Ionicons name="add" size={22} color={theme.color.ink} /></Pressable>
                </View>
                <Text style={[form.meta, { textAlign: 'center' }]}>
                  {bundle.name} · ${bundle.price_per_seat.toLocaleString('en-US')}/seat · about ${(bundle.price_per_seat * n).toLocaleString('en-US')}
                </Text>
              </Card>
              <SectionTitle title="Budget" />
              <ChoiceRow options={cat.budget_bands.map((b) => ({ value: b, label: b }))} value={budget} onChange={setBudget} />
              <SectionTitle title="Timeline" />
              <ChoiceRow options={cat.timelines.map((t) => ({ value: t, label: t }))} value={timeline} onChange={setTimeline} />
              <SectionTitle title="Best phone number (optional)" />
              <TextInput value={phone} onChangeText={setPhone} placeholder="+1 555 0100" placeholderTextColor={theme.color.faint} keyboardType="phone-pad" style={form.input} />
              <View style={{ marginTop: 16 }}>
                <Button label="Get my quote" icon="send" disabled={!budget || !timeline} onPress={() => void sendDetails()} />
              </View>
              <Text style={form.tiny}>{OFFLINE_NOTE}</Text>
            </>
          ) : booked ? (
            <Card style={{ padding: 16, gap: 6, marginTop: 12 }}>
              <Pill label="Booked" tone="ok" icon="checkmark-circle" />
              <Text style={form.h2}>{fmtDate(booked.date, { weekday: 'long', month: 'long', day: 'numeric' })} · {booked.time}</Text>
              <Text style={form.meta}>{booked.topic} · {booked.channel} · with {booked.rep}</Text>
            </Card>
          ) : days.length === 0 ? (
            <Empty icon="calendar-outline" title="No times on this device yet" body="Ask OneChat about a consultation while you're online and the open slots sync here." />
          ) : (
            <>
              <SectionTitle title="What would you like to cover?" />
              <ChoiceRow options={cat.consult_topics.map((t) => ({ value: t, label: t }))} value={topic} onChange={setTopic} />
              <SectionTitle title="Day" />
              <ChoiceRow options={days.map((d) => ({ value: d.date, label: short(d.date), disabled: !d.slots.some((s) => s.open > 0) }))} value={date} onChange={(d) => { setDate(d); setTime(undefined); }} />
              <SectionTitle title="Time" />
              <ChoiceRow options={slots.map((s) => ({ value: s.time, label: s.open > 0 ? s.time : `${s.time} · full`, disabled: s.open <= 0 }))} value={time} onChange={setTime} />
              <SectionTitle title="How" />
              <ChoiceRow options={cat.consult_channels.map((c) => ({ value: c, label: c }))} value={channel} onChange={setChannel} />
              <View style={{ marginTop: 16 }}>
                <Button label={date && time ? `Book ${short(date)} at ${time}` : 'Choose a time'} icon="calendar" disabled={!date || !time} onPress={() => void book()} />
              </View>
              <Text style={form.tiny}>Free, 45 minutes, no obligation. {OFFLINE_NOTE}</Text>
            </>
          )}
        </>
      )}
    </ScrollView>
  );
}
