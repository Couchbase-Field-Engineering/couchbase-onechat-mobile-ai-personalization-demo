import { useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { ScrollView, Text } from 'react-native';
import { useData } from '@/src/data/DataContext';
import { theme } from '@/src/theme';
import { Button, Card, Pill } from '@/src/ui/components';
import { form, OFFLINE_NOTE } from '@/src/ui/form';
import { RequestTracker } from '@/src/ui/RequestTracker';

const TOOL: Record<string, { label: string; note: string }> = {
  checkout_cart: { label: 'Place order', note: 'Charged to the card on your account. Any valid cart offer is applied.' },
  reschedule_delivery: { label: 'Move delivery', note: 'Free to change until the order is out for delivery.' },
  start_return: { label: 'Start a return', note: 'Returns are free. The Returns Agent processes it and remembers the outcome.' },
  issue_goodwill_credit: { label: 'Request a goodwill credit', note: "Goodwill credits are reviewed by a care supervisor before they're applied. You'll see their decision here." },
  book_consultation: { label: 'Book consultation', note: 'Free, 45 minutes. A calendar invite is sent to your email.' },
  submit_lead_details: { label: 'Share details', note: 'Used to size your quote and assign a specialist.' },
  reset_password: { label: 'Reset password', note: "You'll approve a prompt in your authenticator app, then choose a new password within 15 minutes." },
  request_system_access: { label: 'Request access', note: 'A standard system: granted as soon as the request is processed.' },
  request_privileged_access: { label: 'Request privileged access', note: "This system holds customer, financial or production data. Your request is held for approval in Couchbase Labs Agent Operations Manager before access is granted." },
  complete_onboarding_task: { label: 'Complete task', note: 'Marked complete on your onboarding checklist.' },
  request_time_off: { label: 'Request time off', note: 'Goes to your manager for approval.' },
  enroll_benefits: { label: 'Enroll in benefits', note: 'Coverage starts the first of next month.' },
};

/** One-tap actions from For You and Chat land here before they're queued. */
export default function Confirm() {
  const { tool = '', args = '{}', title = '', price = '' } = useLocalSearchParams<{ tool: string; args: string; title: string; price: string }>();
  const { request } = useData();
  const [reqId, setReqId] = useState<string | null>(null);
  const parsed = JSON.parse(args) as Record<string, unknown>;
  const t = TOOL[tool];

  const submit = async () => {
    const req = await request(tool, parsed, title || t?.label || tool);
    setReqId(req._id);
  };

  return (
    <ScrollView contentContainerStyle={form.body}>
      {reqId ? <RequestTracker id={reqId} onRetry={() => setReqId(null)} /> : (
        <Card style={{ padding: 18, gap: 12 }}>
          <Pill label={t?.label ?? tool} tone="ink" />
          <Text style={form.h2}>{title}</Text>
          {price ? <Text style={[form.h3, { color: theme.color.red }]}>{price}</Text> : null}
          {typeof parsed.reason === 'string' ? <Text style={form.meta}>Reason: {parsed.reason}</Text> : null}
          {typeof parsed.justification === 'string' ? <Text style={form.meta}>Justification: {parsed.justification}</Text> : null}
          <Text style={form.meta}>{t?.note ?? ''}</Text>
          <Button label="Confirm" icon="checkmark" onPress={() => void submit()} />
          <Text style={form.tiny}>{OFFLINE_NOTE}</Text>
        </Card>
      )}
    </ScrollView>
  );
}
