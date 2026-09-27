import 'server-only';
import { api } from './api';

export async function features(): Promise<Record<string, boolean>> {
  try {
    return (await api<{ features: Record<string, boolean> }>('/site/features')).features;
  } catch {
    return {}; // Public releases fail closed; Home and MeraAdmin remain reachable.
  }
}
