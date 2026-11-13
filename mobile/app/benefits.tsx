import { Ionicons } from '@expo/vector-icons';
import { useState } from 'react';
import { Pressable, ScrollView, Text, View } from 'react-native';
import { useData } from '@/src/data/DataContext';
import { theme } from '@/src/theme';
import { Button, Card, daysBetween, Empty, fmtDate, Pill, SectionTitle } from '@/src/ui/components';
import { form, OFFLINE_NOTE } from '@/src/ui/form';
import { RequestTracker } from '@/src/ui/RequestTracker';

type Kind = 'medical' | 'dental' | 'vision';
const TITLE: Record<Kind, string> = { medical: 'Medical', dental: 'Dental (optional)', vision: 'Vision (optional)' };

/** Benefits enrollment from the plans in the Team Handbook document (employees channel). */
export default function Benefits() {
  const { snap, request } = useData();
  const p = snap.profile;
  const hb = snap.handbook;
  const [pick, setPick] = useState<Record<Kind, string | undefined>>({ medical: undefined, dental: undefined, vision: undefined });
  const [k401, setK401] = useState(4);
  const [reqId, setReqId] = useState<string | null>(null);
  if (!p) return null;
  if (!hb || p.audience !== 'employee' || !p.hr) {
    return <Empty icon="lock-closed-outline" title="Team members only" body="Benefits are part of the Larkfield team workspace." />;
  }
  const b = p.hr.benefits;
  const plans = hb.benefit_plans;
  const cost = (['medical', 'dental', 'vision'] as Kind[]).reduce((n, k) => n + (plans[k].find((x) => x.id === pick[k])?.employee_cost_per_paycheck ?? 0), 0);
  const left = b.enrollment_deadline ? daysBetween(b.enrollment_deadline, p.export_date) : null;

  const submit = async () => {
    if (!pick.medical) return;
    const names = (['medical', 'dental', 'vision'] as Kind[]).map((k) => plans[k].find((x) => x.id === pick[k])?.name).filter(Boolean).join(', ');
    const req = await request('enroll_benefits', { medical: pick.medical, dental: pick.dental ?? '', vision: pick.vision ?? '', k401_pct: k401 }, `Enroll · ${names}`);
    setReqId(req._id);
  };

  if (b.enrolled && !reqId) {
    const name = (id: string | null) => (id ? [...plans.medical, ...plans.dental, ...plans.vision].find((x) => x.id === id)?.name : null) ?? 'Waived';
    return (
      <ScrollView contentContainerStyle={form.body}>
        <Card style={{ padding: 16, gap: 8 }}>
          <Pill label="Enrolled" tone="ok" icon="checkmark-circle" />
          <Text style={form.h2}>You're covered</Text>
          <Text style={form.meta}>Medical: {name(b.medical)} · Dental: {name(b.dental)} · Vision: {name(b.vision)}</Text>
          <Text style={form.meta}>401(k): {b.k401_pct}% of pay · Larkfield matches up to {hb.k401_match_pct}%</Text>
          <Text style={form.meta}>Changes open again at annual enrollment in November, or after a qualifying life event.</Text>
        </Card>
      </ScrollView>
    );
  }

  return (
    <ScrollView contentContainerStyle={form.body}>
      {reqId ? <RequestTracker id={reqId} onRetry={() => setReqId(null)} /> : (
        <>
          <Card style={{ padding: 16, gap: 6 }}>
            <View style={form.rowBetween}>
              <Text style={form.h2}>Choose your benefits</Text>
              {left !== null ? <Pill label={`${left} days left`} tone={left <= 7 ? 'red' : 'orange'} icon="time-outline" /> : null}
            </View>
            <Text style={form.meta}>Your new-hire window closes {fmtDate(b.enrollment_deadline, { weekday: 'long', month: 'long', day: 'numeric' })}. Coverage starts the first of next month.</Text>
          </Card>
          {(['medical', 'dental', 'vision'] as Kind[]).map((k) => (
            <View key={k}>
              <SectionTitle title={TITLE[k]} />
              {plans[k].map((pl) => (
                <Pressable key={pl.id} onPress={() => setPick((s) => ({ ...s, [k]: s[k] === pl.id && k !== 'medical' ? undefined : pl.id }))}>
                  <Card style={[form.opt, pick[k] === pl.id && form.optSel]}>
                    <View style={{ flex: 1, gap: 3 }}>
                      <Text style={form.h3}>{pl.name}</Text>
                      <Text style={form.meta}>{pl.blurb}</Text>
                    </View>
                    <View style={{ alignItems: 'flex-end', gap: 4 }}>
                      <Text style={{ fontWeight: '700', color: theme.color.ink }}>${pl.employee_cost_per_paycheck}</Text>
                      <Text style={[form.meta, { fontSize: 10 }]}>per paycheck</Text>
                    </View>
                    <Ionicons name={pick[k] === pl.id ? 'radio-button-on' : 'radio-button-off'} size={22} color={theme.color.ink} />
                  </Card>
                </Pressable>
              ))}
            </View>
          ))}
          <SectionTitle title="401(k) contribution" />
          <Card style={{ padding: 16, gap: 8 }}>
            <View style={form.stepper}>
              <Pressable onPress={() => setK401((v) => Math.max(0, v - 1))} style={form.step}><Ionicons name="remove" size={22} color={theme.color.ink} /></Pressable>
              <Text style={form.big}>{k401}%</Text>
              <Pressable onPress={() => setK401((v) => Math.min(50, v + 1))} style={form.step}><Ionicons name="add" size={22} color={theme.color.ink} /></Pressable>
            </View>
            <Text style={[form.meta, { textAlign: 'center' }]}>
              Larkfield matches dollar for dollar up to {hb.k401_match_pct}%{k401 < hb.k401_match_pct ? ` - you're leaving ${hb.k401_match_pct - k401}% of match on the table` : ''}.
            </Text>
          </Card>
          <View style={{ marginTop: 16 }}>
            <Button label={pick.medical ? `Enroll · $${cost} per paycheck` : 'Choose a medical plan'} icon="medkit" disabled={!pick.medical} onPress={() => void submit()} />
          </View>
          <Text style={form.tiny}>{OFFLINE_NOTE}</Text>
        </>
      )}
    </ScrollView>
  );
}
