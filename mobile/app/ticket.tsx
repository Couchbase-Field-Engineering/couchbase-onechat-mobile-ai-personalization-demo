import { useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { ScrollView, Text, TextInput, View } from 'react-native';
import { useData } from '@/src/data/DataContext';
import { theme } from '@/src/theme';
import { Button, Card, Empty, SectionTitle } from '@/src/ui/components';
import { ChoiceRow } from '@/src/ui/Choice';
import { form, OFFLINE_NOTE } from '@/src/ui/form';
import { RequestTracker } from '@/src/ui/RequestTracker';

/** IT help desk ticket. Categories come from the Team Handbook document, which only a team member's phone has. */
export default function Ticket() {
  const params = useLocalSearchParams<{ category?: string; summary?: string }>();
  const { snap, request } = useData();
  const hb = snap.handbook;
  const p = snap.profile;
  const [category, setCategory] = useState<string | undefined>(params.category);
  const [priority, setPriority] = useState('normal');
  const [summary, setSummary] = useState(params.summary ?? '');
  const [reqId, setReqId] = useState<string | null>(null);
  if (!p) return null;
  if (!hb || p.audience !== 'employee') {
    return <Empty icon="lock-closed-outline" title="Team members only" body="The IT help desk is part of the Larkfield team workspace. This phone has no Team Handbook data - Sync Gateway never sent it." />;
  }
  const cat = hb.it_categories.find((c) => c.id === category);
  const device = p.it?.devices?.[0];

  const submit = async () => {
    if (!cat) return;
    const req = await request('create_it_ticket', { category: cat.id, summary: summary.trim(), priority }, `Help desk · ${cat.name}`);
    setReqId(req._id);
  };

  return (
    <ScrollView contentContainerStyle={form.body} keyboardShouldPersistTaps="handled">
      {reqId ? <RequestTracker id={reqId} onRetry={() => setReqId(null)} /> : (
        <>
          {device ? (
            <Card style={{ padding: 16, gap: 4 }}>
              <Text style={form.meta}>YOUR DEVICE</Text>
              <Text style={form.h3}>{device.model}</Text>
              <Text style={form.meta}>{device.os} · asset {device.asset_tag} · attached to the ticket automatically</Text>
            </Card>
          ) : null}
          <SectionTitle title="What's it about?" />
          <ChoiceRow options={hb.it_categories.map((c) => ({ value: c.id, label: c.name }))} value={category} onChange={setCategory} />
          {cat ? <Text style={[form.meta, { marginTop: 6 }]}>{cat.queue} team · first response within {cat.sla_hours} business hours</Text> : null}
          <SectionTitle title="What's happening?" />
          <TextInput
            value={summary} onChangeText={setSummary} multiline placeholder="e.g. VPN client won't connect from home"
            placeholderTextColor={theme.color.faint} style={[form.input, { minHeight: 90, textAlignVertical: 'top' }]}
          />
          <SectionTitle title="Priority" />
          <ChoiceRow options={hb.it_priorities.map((x) => ({ value: x, label: x[0].toUpperCase() + x.slice(1) }))} value={priority} onChange={setPriority} />
          <View style={{ marginTop: 16 }}>
            <Button label="Open ticket" icon="construct" disabled={!cat || summary.trim().length < 5} onPress={() => void submit()} />
          </View>
          <Text style={form.tiny}>{OFFLINE_NOTE}</Text>
        </>
      )}
    </ScrollView>
  );
}
