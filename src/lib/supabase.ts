import { createClient } from "@supabase/supabase-js";

const url = process.env.NEXT_PUBLIC_SUPABASE_URL!;
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!;

export const supabase = createClient(url, anonKey);

export type TaskStatus = "todo" | "doing" | "done";

export type TaskCategory = "board" | "longterm";

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
};

export const STATUSES: { key: TaskStatus; label: string }[] = [
  { key: "todo", label: "To Do" },
  { key: "doing", label: "Doing" },
  { key: "done", label: "Done" },
];

export const STATUS_COLORS: Record<
  TaskStatus,
  { dot: string; chip: string; ring: string }
> = {
  todo: {
    dot: "bg-blue-500",
    chip: "bg-blue-500/15 text-blue-300 hover:bg-blue-500/25",
    ring: "ring-blue-500/40",
  },
  doing: {
    dot: "bg-amber-500",
    chip: "bg-amber-500/15 text-amber-300 hover:bg-amber-500/25",
    ring: "ring-amber-500/40",
  },
  done: {
    dot: "bg-emerald-500",
    chip: "bg-emerald-500/15 text-emerald-300 hover:bg-emerald-500/25 line-through decoration-emerald-500/50",
    ring: "ring-emerald-500/40",
  },
};
