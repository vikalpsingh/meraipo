export type JobRun = {
  id: string;
  job_name: string;
  status: string;
  error: string | null;
  summary?: string;
  trigger: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds?: number | null;
  counters: Record<string, number> | null;
  parameters?: Record<string, unknown>;
};
export type ScheduledJob = {
  name: string;
  label: string;
  schedule: string;
  paused: boolean;
  source_enabled?: boolean;
  exchange: string | null;
  configurable: boolean;
  times?: string[];
  next_run: string | null;
  last: JobRun | null;
  last_success: JobRun | null;
  schedule_note?: string;
};
