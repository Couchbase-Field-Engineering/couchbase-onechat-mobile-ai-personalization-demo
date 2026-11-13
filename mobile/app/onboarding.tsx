import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { useState } from 'react';
import { ScrollView, Text, TextInput, View } from 'react-native';
import { useData } from '@/src/data/DataContext';
import { theme } from '@/src/theme';
import { Button, Card, daysBetween, Empty, fmtDate, Pill, SectionTitle } from '@/src/ui/components';
import { form, OFFLINE_NOTE } from '@/src/ui/form';
import { RequestTracker } from '@/src/ui/RequestTracker';

const KIND: Record<string, string> = { form: 'Form', sign: 'Signature', training: 'Training' };

/** New-hire paperwork: every task is a request queued in Couchbase Lite, so a form can be signed with no signal. */
export default function Onboarding() {
  const { snap, request } = useData();
  const p = snap.profile;
  const [open, setOpen] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [reqId, setReqId] = useState<string | null>(null);
  if (!p) return null;
  if (p.audience !== 'employee' || !p.onboarding) {
    return <Empty icon="lock-closed-outline" title="Team members only" body="Onboarding is part of the Larkfield team workspace." />;
  }
  const today = p.export_date;
  const tasks = [...p.onboarding.tasks].sort((a, b) => (a.status === b.status ? (a.due_date < b.due_date ? -1 : 1) : a.status === 'complete' ? 1 : -1));
  const done = tasks.filter((t) => t.status === 'complete').length;
  const detail = (id: string) => snap.handbook?.onboarding_tasks.find((t) => t.task_id === id)?.detail ?? '';
  // Requests still on their way count as in flight, so a task isn't submitted twice.
  const inFlight = new Set(snap.requests.filter((r) => r.tool === 'complete_onboarding_task' && ['pending', 'processing'].includes(r.status)).map((r) => String(r.args.task_id)));

  const complete = async (taskId: string, title: string, sign: boolean) => {
    const req = await request('complete_onboarding_task', sign ? { task_id: taskId, acknowledgment: name.trim() } : { task_id: taskId }, sign ? `Signed · ${title}` : `Completed · ${title}`);
    setReqId(req._id);
    setOpen(null);
    setName('');
  };

  return (
    <ScrollView contentContainerStyle={form.body} keyboardShouldPersistTaps="handled">
      <Card style={{ padding: 16, gap: 8 }}>
        <View style={form.rowBetween}>
          <Text style={form.h2}>{done} of {tasks.length} complete</Text>
          <Pill label={`Day ${daysBetween(today, p.employment?.start_date ?? today) + 1}`} tone="ink" />
        </View>
        <View style={{ height: 8, borderRadius: 4, backgroundColor: theme.color.bg, overflow: 'hidden' }}>
          <View style={{ height: 8, borderRadius: 4, backgroundColor: theme.color.red, width: `${Math.round((done / tasks.length) * 100)}%` }} />
        </View>
        <Text style={form.meta}>{p.employment?.title} · {p.employment?.department} · reporting to {p.employment?.manager}</Text>
      </Card>

      {reqId ? <RequestTracker id={reqId} /> : null}

      <SectionTitle title="Your checklist" />
      {tasks.map((t) => {
        const complete_ = t.status === 'complete';
        const d = daysBetween(t.due_date, today);
        const sending = inFlight.has(t.task_id);
        return (
          <Card key={t.task_id} style={{ padding: 14, marginBottom: 10, gap: 8, opacity: complete_ ? 0.7 : 1 }}>
            <View style={{ flexDirection: 'row', gap: 10, alignItems: 'center' }}>
              <Ionicons name={complete_ ? 'checkmark-circle' : sending ? 'cloud-upload-outline' : 'ellipse-outline'} size={22} color={complete_ ? theme.color.ok : theme.color.red} />
              <View style={{ flex: 1 }}>
                <Text style={{ fontWeight: '700', color: theme.color.text }}>{t.title}</Text>
                <Text style={form.meta}>
                  {KIND[t.kind]} · {complete_ ? `done ${fmtDate(t.completed_at)}` : sending ? 'sending…' : d < 0 ? `overdue since ${fmtDate(t.due_date)}` : d === 0 ? 'due today' : d === 1 ? 'due tomorrow' : `due ${fmtDate(t.due_date)}`}
                </Text>
              </View>
              {!complete_ && !sending ? (
                t.task_id === 'benefits'
                  ? <Button small label="Choose plans" onPress={() => router.push('/benefits')} />
                  : <Button small kind={open === t.task_id ? 'ghost' : 'primary'} label={open === t.task_id ? 'Close' : t.kind === 'sign' ? 'Sign' : 'Open'} onPress={() => setOpen(open === t.task_id ? null : t.task_id)} />
              ) : null}
            </View>
            {open === t.task_id ? (
              <View style={{ gap: 10, borderTopWidth: 1, borderTopColor: theme.color.border, paddingTop: 10 }}>
                <Text style={form.meta}>{detail(t.task_id)}</Text>
                {t.kind === 'sign' ? (
                  <>
                    <TextInput value={name} onChangeText={setName} placeholder="Type your full name to sign" placeholderTextColor={theme.color.faint} style={form.input} autoCapitalize="words" />
                    <Button label="Sign and submit" icon="create" disabled={name.trim().length < 3} onPress={() => void complete(t.task_id, t.title, true)} />
                  </>
                ) : (
                  <Button label={t.kind === 'training' ? "I've completed the course" : 'Submit'} icon="checkmark" onPress={() => void complete(t.task_id, t.title, false)} />
                )}
              </View>
            ) : null}
          </Card>
        );
      })}
      <Text style={form.tiny}>{OFFLINE_NOTE}</Text>
    </ScrollView>
  );
}
