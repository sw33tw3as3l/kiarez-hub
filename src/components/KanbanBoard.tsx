"use client";

import { STATUSES, STATUS_COLORS, Task, TaskStatus } from "@/lib/supabase";

export default function KanbanBoard({
  tasksByStatus,
  canEdit,
  onAdd,
  onOpen,
  onDelete,
}: {
  tasksByStatus: Record<TaskStatus, Task[]>;
  canEdit: boolean;
  onAdd: (status: TaskStatus) => void;
  onOpen: (task: Task) => void;
  onDelete: (task: Task) => void;
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
              <div
                key={task.id}
                onClick={() => onOpen(task)}
                className="group relative cursor-pointer rounded-xl border border-neutral-800 bg-neutral-900 p-3 text-left text-sm shadow-sm transition hover:border-neutral-700 hover:bg-neutral-800"
              >
                <div
                  className={
                    task.status === "done"
                      ? "pr-5 text-neutral-400 line-through decoration-neutral-600"
                      : "pr-5 text-neutral-100"
                  }
                >
                  {task.title}
                </div>
                {task.description && (
                  <div className="mt-1 truncate pr-5 text-xs text-neutral-500">
                    {task.description}
                  </div>
                )}

                {canEdit && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onDelete(task);
                    }}
                    className="absolute right-2 top-2 hidden h-5 w-5 items-center justify-center rounded text-neutral-500 hover:bg-neutral-700 hover:text-red-400 group-hover:flex"
                    title="Delete task"
                  >
                    ✕
                  </button>
                )}
              </div>
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
