import { createClient } from "@supabase/supabase-js";

const url = process.env.NEXT_PUBLIC_SUPABASE_URL!;
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!;

export const supabase = createClient(url, anonKey);

export type TaskStatus = "todo" | "doing" | "done";

export type TaskCategory = "board" | "longterm";

export type TaskEffort = "15m" | "30m" | "1h" | "2h" | "half_day" | "day_plus";

export type Goal = {
  id: string;
  title: string;
  description: string | null;
  target_date: string | null;
  position: number;
  archived: boolean;
  created_at: string;
};

export type Task = {
  id: string;
  title: string;
  description: string | null;
  status: TaskStatus;
  category: TaskCategory;
  due_date: string | null;
  due_time: string | null;
  position: number;
  created_at: string;
  goal_id: string | null;
  outcome: string | null;
  effort: TaskEffort | null;
  next_action: string | null;
};

export const STATUSES: { key: TaskStatus; label: string }[] = [
  { key: "todo", label: "To Do" },
  { key: "doing", label: "Doing" },
  { key: "done", label: "Done" },
];

export const EFFORTS: { key: TaskEffort; label: string }[] = [
  { key: "15m", label: "15m" },
  { key: "30m", label: "30m" },
  { key: "1h", label: "1h" },
  { key: "2h", label: "2h" },
  { key: "half_day", label: "Half day" },
  { key: "day_plus", label: "Day+" },
];

export const EFFORT_LABELS: Record<TaskEffort, string> = Object.fromEntries(
  EFFORTS.map((e) => [e.key, e.label])
) as Record<TaskEffort, string>;

// Anything at or above half a day is too big to live on the day board:
// it has to be split into smaller tasks or promoted to Long-term.
const OVERSIZED: TaskEffort[] = ["half_day", "day_plus"];

export function isOversized(effort: TaskEffort | "" | null) {
  return !!effort && OVERSIZED.includes(effort);
}

// A task is only "defined" once all four Tier 1 fields are filled in.
export function isDefined(task: Task) {
  return !!(task.goal_id && task.outcome && task.effort && task.next_action);
}

export const STATUS_COLORS: Record<
  TaskStatus,
  { dot: string; chip: string; ring: string }
> = {
  todo: {
    dot: "bg-ink-faint",
    chip: "bg-surf-high text-ink-dim hover:bg-surf-highest",
    ring: "ring-ink-faint/40",
  },
  doing: {
    dot: "bg-ember",
    chip: "bg-ember-deep/50 text-on-ember-deep hover:bg-ember-deep/70",
    ring: "ring-ember/40",
  },
  done: {
    dot: "bg-success",
    chip: "bg-success-deep/50 text-on-success-deep hover:bg-success-deep/70 line-through decoration-success/50",
    ring: "ring-success/40",
  },
};
