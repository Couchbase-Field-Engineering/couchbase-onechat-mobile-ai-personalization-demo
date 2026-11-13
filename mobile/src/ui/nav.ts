import { router } from 'expo-router';
import type { Cta } from '../types';
import type { IconName } from './components';

export const KIND_ICON: Record<string, IconName> = {
  order: 'cube',
  return: 'return-down-back',
  cart: 'cart',
  product: 'pricetag',
  consult: 'calendar',
  lead: 'create',
  onboarding: 'clipboard',
  benefits: 'medkit',
  ticket: 'construct',
  it: 'key',
  timeoff: 'sunny',
  reward: 'star',
};

export const KIND_LABEL: Record<string, string> = {
  order: 'Order tracking',
  return: 'Returns & exchanges',
  cart: 'Your cart',
  product: 'Picked for you',
  consult: 'Consultation',
  lead: 'Your quote',
  onboarding: 'Onboarding',
  benefits: 'Benefits',
  ticket: 'Help desk',
  it: 'IT',
  timeoff: 'Time off',
  reward: 'Rewards',
};

export const ACTIVITY_ICON: Record<string, IconName> = {
  delivery: 'calendar', return: 'return-down-back', exchange: 'swap-horizontal', credit: 'gift', order: 'cube', lead: 'create',
  consultation: 'calendar', ticket: 'construct', password: 'key', access: 'lock-open', timeoff: 'sunny', benefits: 'medkit',
  onboarding: 'clipboard',
};

/**
 * Open what's behind a feed card or a chat suggestion:
 *  - `screen`: a purpose-built screen (order, return, consult, ticket, onboarding, benefits, timeoff)
 *  - `tool`:   a one-tap action, confirmed on /confirm and queued offline-first
 *  - `ask`:    a question for the Chat tab (queued through `queueAsk`)
 */
export function openAction(a: Cta, opts: { title?: string; price?: string; queueAsk?: (q: string) => void } = {}) {
  if (a.ask) {
    opts.queueAsk?.(a.ask);
    router.navigate('/(tabs)');
    return;
  }
  if (a.screen) {
    router.push({ pathname: `/${a.screen}` as never, params: Object.fromEntries(Object.entries(a.args ?? {}).map(([k, v]) => [k, String(v)])) });
    return;
  }
  if (a.tool) {
    router.push({
      pathname: '/confirm',
      params: { tool: a.tool, args: JSON.stringify(a.args ?? {}), title: opts.title ?? a.label, price: opts.price ?? '' },
    });
  }
}
