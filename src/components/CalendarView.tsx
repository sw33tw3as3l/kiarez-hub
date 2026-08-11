"use client";

import { useMemo, useState } from "react";
import { STATUS_COLORS, Task } from "@/lib/supabase";

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MAX_VISIBLE = 4;

function fmt(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(
    2,
    "0"
  )}-${String(date.getDate()).padStart(2, "0")}`;
}

export default function CalendarView({
  tasksByDate,
  canEdit,
  onAdd,
  onOpen,
}: {
  tasksByDate: Record<string, Task[]>;
  canEdit: boolean;
  onAdd: (dateStr: string) => void;
  onOpen: (task: Task) => void;
}) {
  const today = new Date();
  const todayStr = fmt(today);
  const [year, setYear] = useState(today.getFullYear());
  const [month, setMonth] = useState(today.getMonth());
  const [overflowDate, setOverflowDate] = useState<string | null>(null);

  const cells = useMemo(() => {
    const firstOfMonth = new Date(year, month, 1);
    const start = new Date(firstOfMonth);
    start.setDate(start.getDate() - start.getDay());

    return Array.from({ length: 42 }, (_, i) => {
      const date = new Date(start);
      date.setDate(start.getDate() + i);
      return date;
    });
  }, [year, month]);

  function shiftMonth(delta: number) {
    const d = new Date(year, month + delta, 1);
    setYear(d.getFullYear());
    setMonth(d.getMonth());
  }

  function goToday() {
    setYear(today.getFullYear());
    setMonth(today.getMonth());
  }

  const sortedTasks = (dateStr: string) =>
    [...(tasksByDate[dateStr] ?? [])].sort((a, b) => {
      if (!a.due_time && !b.due_time) return 0;
      if (!a.due_time) return 1;
      if (!b.due_time) return -1;
      return a.due_time.localeCompare(b.due_time);
    });

  return (
    <div className="p-6">
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <button
            onClick={goToday}
            className="rounded-lg border border-neutral-800 px-3 py-1.5 text-sm text-neutral-300 hover:bg-neutral-800"
          >
            Today
          </button>
          <button
            onClick={() => shiftMonth(-1)}
            className="rounded-lg px-2 py-1.5 text-neutral-400 hover:bg-neutral-800"
          >
            ←
          </button>
          <button
            onClick={() => shiftMonth(1)}
            className="rounded-lg px-2 py-1.5 text-neutral-400 hover:bg-neutral-800"
          >
            →
          </button>
        </div>
        <h2 className="text-base font-semibold text-neutral-100">
          {new Date(year, month, 1).toLocaleString("en-US", {
            month: "long",
            year: "numeric",
          })}
        </h2>
        <div className="w-[132px]" />
      </div>

      <div className="grid grid-cols-7 gap-px overflow-hidden rounded-xl border border-neutral-800 bg-neutral-800">
        {WEEKDAYS.map((d) => (
          <div
            key={d}
            className="bg-neutral-900 py-2.5 text-center text-sm font-medium text-neutral-500"
          >
            {d}
          </div>
        ))}

        {cells.map((date) => {
          const dateStr = fmt(date);
          const inMonth = date.getMonth() === month;
          const isToday = dateStr === todayStr;
          const dayTasks = sortedTasks(dateStr);
          const visible = dayTasks.slice(0, MAX_VISIBLE);
          const hidden = dayTasks.length - visible.length;

          return (
            <div
              key={dateStr}
              className={`group relative min-h-[144px] bg-neutral-950 p-2 text-left ${
                inMonth ? "" : "opacity-40"
              }`}
            >
              <div className="mb-1.5 flex items-center justify-between">
                <span
                  className={`flex h-7 w-7 items-center justify-center rounded-full text-sm ${
                    isToday
                      ? "bg-red-600 font-semibold text-white"
                      : "text-neutral-400"
                  }`}
                >
                  {date.getDate()}
                </span>
                {canEdit && (
                  <button
                    onClick={() => onAdd(dateStr)}
                    className="hidden h-6 w-6 items-center justify-center rounded text-neutral-500 hover:bg-neutral-800 hover:text-neutral-200 group-hover:flex"
                  >
                    +
                  </button>
                )}
              </div>

              <div className="flex flex-col gap-1">
                {visible.map((t) => (
                  <button
                    key={t.id}
                    onClick={() => onOpen(t)}
                    className={`truncate rounded px-1.5 py-1 text-left text-xs ${STATUS_COLORS[t.status].chip}`}
                    title={t.title}
                  >
                    {t.due_time && (
                      <span className="opacity-70">
                        {t.due_time.slice(0, 5)}{" "}
                      </span>
                    )}
                    {t.title}
                  </button>
                ))}
                {hidden > 0 && (
                  <button
                    onClick={() => setOverflowDate(dateStr)}
                    className="px-1.5 text-left text-xs text-neutral-500 hover:text-neutral-300"
                  >
                    +{hidden} more
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {overflowDate && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
          onClick={() => setOverflowDate(null)}
        >
          <div
            className="w-full max-w-sm rounded-2xl border border-neutral-800 bg-neutral-900 p-4 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-neutral-200">
                {new Date(overflowDate).toLocaleDateString("en-US", {
                  weekday: "long",
                  month: "long",
                  day: "numeric",
                })}
              </h3>
              <button
                onClick={() => setOverflowDate(null)}
                className="rounded p-1 text-neutral-500 hover:bg-neutral-800 hover:text-neutral-300"
              >
                ✕
              </button>
            </div>
            <div className="flex flex-col gap-1">
              {sortedTasks(overflowDate).map((t) => (
                <button
                  key={t.id}
                  onClick={() => {
                    setOverflowDate(null);
                    onOpen(t);
                  }}
                  className={`rounded-lg px-2 py-1.5 text-left text-sm ${STATUS_COLORS[t.status].chip}`}
                >
                  {t.due_time && (
                    <span className="opacity-70">
                      {t.due_time.slice(0, 5)}{" "}
                    </span>
                  )}
                  {t.title}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
