"use client";

import { useEffect, useMemo, useState } from "react";
import { supabase, Task, TaskStatus } from "@/lib/supabase";

const COLUMNS: { key: TaskStatus; label: string }[] = [
  { key: "todo", label: "To Do" },
  { key: "doing", label: "Doing" },
  { key: "done", label: "Done" },
];

const EDIT_PIN = process.env.NEXT_PUBLIC_EDIT_PIN;

export default function Board() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [view, setView] = useState<"board" | "calendar">("board");
  const [canEdit, setCanEdit] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newDue, setNewDue] = useState("");
  const [addingTo, setAddingTo] = useState<TaskStatus | null>(null);

  useEffect(() => {
    supabase
      .from("tasks")
      .select("*")
      .order("position", { ascending: true })
      .then(({ data }) => setTasks(data ?? []));

    const channel = supabase
      .channel("tasks-realtime")
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "tasks" },
        () => {
          supabase
            .from("tasks")
            .select("*")
            .order("position", { ascending: true })
            .then(({ data }) => setTasks(data ?? []));
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, []);

  const tasksByStatus = useMemo(() => {
    const map: Record<TaskStatus, Task[]> = { todo: [], doing: [], done: [] };
    for (const t of tasks) map[t.status].push(t);
    return map;
  }, [tasks]);

  const tasksByDate = useMemo(() => {
    const map: Record<string, Task[]> = {};
    for (const t of tasks) {
      if (!t.due_date) continue;
      (map[t.due_date] ??= []).push(t);
    }
    return map;
  }, [tasks]);

  function tryUnlock() {
    const pin = prompt("PIN برای ویرایش:");
    if (pin && EDIT_PIN && pin === EDIT_PIN) {
      setCanEdit(true);
    } else if (pin) {
      alert("PIN اشتباهه");
    }
  }

  async function addTask(status: TaskStatus) {
    if (!newTitle.trim()) return;
    const position = tasksByStatus[status].length;
    await supabase.from("tasks").insert({
      title: newTitle.trim(),
      status,
      due_date: newDue || null,
      position,
    });
    setNewTitle("");
    setNewDue("");
    setAddingTo(null);
  }

  async function moveTask(task: Task, status: TaskStatus) {
    await supabase.from("tasks").update({ status }).eq("id", task.id);
  }

  async function deleteTask(task: Task) {
    if (!confirm(`حذف "${task.title}"?`)) return;
    await supabase.from("tasks").delete().eq("id", task.id);
  }

  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-100">
      <header className="flex items-center justify-between border-b border-neutral-800 px-6 py-4">
        <h1 className="text-xl font-semibold tracking-tight">Kiarez Hub</h1>
        <div className="flex items-center gap-3">
          <div className="flex rounded-lg border border-neutral-800 overflow-hidden text-sm">
            <button
              onClick={() => setView("board")}
              className={`px-3 py-1.5 ${view === "board" ? "bg-neutral-800" : ""}`}
            >
              Board
            </button>
            <button
              onClick={() => setView("calendar")}
              className={`px-3 py-1.5 ${view === "calendar" ? "bg-neutral-800" : ""}`}
            >
              Calendar
            </button>
          </div>
          {canEdit ? (
            <span className="text-xs text-emerald-400">حالت ویرایش</span>
          ) : (
            <button
              onClick={tryUnlock}
              className="text-xs text-neutral-400 hover:text-neutral-200 underline"
            >
              ویرایش
            </button>
          )}
        </div>
      </header>

      {view === "board" ? (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 p-6">
          {COLUMNS.map((col) => (
            <div key={col.key} className="rounded-xl bg-neutral-900 p-3">
              <div className="mb-2 flex items-center justify-between px-1">
                <h2 className="text-sm font-medium text-neutral-300">
                  {col.label}
                </h2>
                <span className="text-xs text-neutral-500">
                  {tasksByStatus[col.key].length}
                </span>
              </div>

              <div className="flex flex-col gap-2">
                {tasksByStatus[col.key].map((task) => (
                  <div
                    key={task.id}
                    className="rounded-lg bg-neutral-800 p-3 text-sm shadow-sm"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <span>{task.title}</span>
                      {canEdit && (
                        <button
                          onClick={() => deleteTask(task)}
                          className="text-neutral-500 hover:text-red-400 text-xs"
                        >
                          ✕
                        </button>
                      )}
                    </div>
                    {task.due_date && (
                      <div className="mt-1 text-xs text-neutral-500">
                        {task.due_date}
                      </div>
                    )}
                    {canEdit && (
                      <div className="mt-2 flex gap-1">
                        {COLUMNS.filter((c) => c.key !== task.status).map(
                          (c) => (
                            <button
                              key={c.key}
                              onClick={() => moveTask(task, c.key)}
                              className="rounded bg-neutral-700 px-2 py-0.5 text-xs hover:bg-neutral-600"
                            >
                              → {c.label}
                            </button>
                          )
                        )}
                      </div>
                    )}
                  </div>
                ))}

                {canEdit &&
                  (addingTo === col.key ? (
                    <div className="rounded-lg bg-neutral-800 p-2">
                      <input
                        autoFocus
                        value={newTitle}
                        onChange={(e) => setNewTitle(e.target.value)}
                        placeholder="عنوان تسک"
                        className="w-full rounded bg-neutral-700 px-2 py-1 text-sm outline-none"
                        onKeyDown={(e) => e.key === "Enter" && addTask(col.key)}
                      />
                      <input
                        type="date"
                        value={newDue}
                        onChange={(e) => setNewDue(e.target.value)}
                        className="mt-1 w-full rounded bg-neutral-700 px-2 py-1 text-sm outline-none"
                      />
                      <div className="mt-1 flex gap-1">
                        <button
                          onClick={() => addTask(col.key)}
                          className="rounded bg-emerald-700 px-2 py-1 text-xs"
                        >
                          افزودن
                        </button>
                        <button
                          onClick={() => setAddingTo(null)}
                          className="rounded bg-neutral-700 px-2 py-1 text-xs"
                        >
                          لغو
                        </button>
                      </div>
                    </div>
                  ) : (
                    <button
                      onClick={() => setAddingTo(col.key)}
                      className="rounded-lg border border-dashed border-neutral-700 py-2 text-xs text-neutral-500 hover:text-neutral-300"
                    >
                      + تسک جدید
                    </button>
                  ))}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <CalendarView tasksByDate={tasksByDate} />
      )}
    </div>
  );
}

function CalendarView({
  tasksByDate,
}: {
  tasksByDate: Record<string, Task[]>;
}) {
  const today = new Date();
  const [year, setYear] = useState(today.getFullYear());
  const [month, setMonth] = useState(today.getMonth()); // 0-indexed

  const firstDay = new Date(year, month, 1);
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const startWeekday = firstDay.getDay();

  const cells: (number | null)[] = [
    ...Array(startWeekday).fill(null),
    ...Array.from({ length: daysInMonth }, (_, i) => i + 1),
  ];

  function shiftMonth(delta: number) {
    const d = new Date(year, month + delta, 1);
    setYear(d.getFullYear());
    setMonth(d.getMonth());
  }

  return (
    <div className="p-6">
      <div className="mb-4 flex items-center justify-between">
        <button
          onClick={() => shiftMonth(-1)}
          className="rounded bg-neutral-800 px-3 py-1 text-sm"
        >
          ←
        </button>
        <h2 className="text-sm font-medium text-neutral-300">
          {firstDay.toLocaleString("default", { month: "long", year: "numeric" })}
        </h2>
        <button
          onClick={() => shiftMonth(1)}
          className="rounded bg-neutral-800 px-3 py-1 text-sm"
        >
          →
        </button>
      </div>

      <div className="grid grid-cols-7 gap-1 text-center text-xs text-neutral-500 mb-1">
        {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((d) => (
          <div key={d}>{d}</div>
        ))}
      </div>

      <div className="grid grid-cols-7 gap-1">
        {cells.map((day, i) => {
          if (day === null) return <div key={i} />;
          const dateStr = `${year}-${String(month + 1).padStart(2, "0")}-${String(
            day
          ).padStart(2, "0")}`;
          const dayTasks = tasksByDate[dateStr] ?? [];
          return (
            <div
              key={i}
              className="min-h-[80px] rounded-lg bg-neutral-900 p-1 text-left"
            >
              <div className="text-xs text-neutral-500">{day}</div>
              <div className="mt-1 flex flex-col gap-0.5">
                {dayTasks.map((t) => (
                  <div
                    key={t.id}
                    className="truncate rounded bg-neutral-800 px-1 py-0.5 text-[11px]"
                    title={t.title}
                  >
                    {t.title}
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
