"use client";

import { STATUSES, STATUS_COLORS, Task, TaskStatus } from "@/lib/supabase";

export default function KanbanBoard({
  tasksByStatus,
  canEdit,
  onAdd,
  onOpen,
}: {
  tasksByStatus: Record<TaskStatus, Task[]>;
  canEdit: boolean;
  onAdd: (status: TaskStatus) => void;
  onOpen: (task: Task) => void;
}) {
  return (
    <div className="grid grid-cols-1 gap-4 p-6 md:grid-cols-3">
      {STATUSES.map((col) => (
        <div key={col.key} className="rounded-2xl bg-neutral-900/60 p-3">
          <div className="mb-3 flex items-center justify-between px-1">
            <div className="flex items-center gap-2">
              <span
                className={`h-2 w-2 rounded-full ${STATUS_COLORS[col.key].dot}`}
              />
              <h2 className="text-sm font-medium text-neutral-300">
                {col.label}
              </h2>
            </div>
            <span className="text-xs text-neutral-500">
              {tasksByStatus[col.key].length}
            </span>
          </div>

          <div className="flex flex-col gap-2">
            {tasksByStatus[col.key].map((task) => (
              <button
                key={task.id}
                onClick={() => onOpen(task)}
                className="rounded-xl border border-neutral-800 bg-neutral-900 p-3 text-left text-sm shadow-sm transition hover:border-neutral-700 hover:bg-neutral-800"
              >
                <div
                  className={
                    task.status === "done"
                      ? "text-neutral-400 line-through decoration-neutral-600"
                      : "text-neutral-100"
                  }
                >
                  {task.title}
                </div>
                {task.description && (
                  <div className="mt-1 truncate text-xs text-neutral-500">
                    {task.description}
                  </div>
                )}
                {task.due_date && (
                  <div className="mt-2 inline-flex items-center gap-1 rounded-full bg-neutral-800 px-2 py-0.5 text-[11px] text-neutral-400">
                    {task.due_date}
                    {task.due_time && ` · ${task.due_time.slice(0, 5)}`}
                  </div>
                )}
              </button>
            ))}

            {canEdit && (
              <button
                onClick={() => onAdd(col.key)}
                className="rounded-xl border border-dashed border-neutral-800 py-2 text-xs text-neutral-500 transition hover:border-neutral-700 hover:text-neutral-300"
              >
                + New task
              </button>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
