"use client";

import { useRef, useState } from "react";
import { STATUSES, Task, TaskCategory, TaskStatus } from "@/lib/supabase";

export type TaskDraft = {
  title: string;
  description: string;
  status: TaskStatus;
  due_date: string;
  due_time: string;
};

export default function TaskModal({
  task,
  category,
  initialStatus,
  initialDate,
  onClose,
  onSave,
  onDelete,
}: {
  task: Task | null;
  category: TaskCategory;
  initialStatus?: TaskStatus;
  initialDate?: string;
  onClose: () => void;
  onSave: (draft: TaskDraft) => Promise<void>;
  onDelete?: () => Promise<void>;
}) {
  const showDate = category === "board";
  const [title, setTitle] = useState(task?.title ?? "");
  const [description, setDescription] = useState(task?.description ?? "");
  const [status, setStatus] = useState<TaskStatus>(
    task?.status ?? initialStatus ?? "todo"
  );
  const [dueDate, setDueDate] = useState(task?.due_date ?? initialDate ?? "");
  const [dueTime, setDueTime] = useState(task?.due_time?.slice(0, 5) ?? "");
  const [saving, setSaving] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [error, setError] = useState("");

  const isEditing = !!task;
  const submitting = useRef(false);

  async function handleSave() {
    if (!title.trim() || submitting.current) return;
    submitting.current = true;
    setSaving(true);
    setError("");
    try {
      await onSave({
        title: title.trim(),
        description: description.trim(),
        status,
        due_date: dueDate,
        due_time: dueDate ? dueTime : "",
      });
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      submitting.current = false;
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!onDelete) return;
    if (!confirmingDelete) {
      setConfirmingDelete(true);
      return;
    }
    setError("");
    try {
      await onDelete();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-2xl border border-neutral-800 bg-neutral-900 p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-neutral-200">
            {isEditing ? "Edit task" : "New task"}
          </h3>
          <button
            onClick={onClose}
            className="rounded p-1 text-neutral-500 hover:bg-neutral-800 hover:text-neutral-300"
          >
            ✕
          </button>
        </div>

        <div className="flex flex-col gap-3">
          <input
            autoFocus
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Task title"
            className="w-full rounded-lg border border-neutral-800 bg-neutral-950 px-3 py-2 text-sm text-neutral-100 outline-none focus:border-neutral-600"
            onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleSave()}
          />

          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Description (optional)"
            rows={3}
            className="w-full resize-none rounded-lg border border-neutral-800 bg-neutral-950 px-3 py-2 text-sm text-neutral-100 outline-none focus:border-neutral-600"
          />

          <div className="flex gap-2">
            <label className="flex-1 text-xs text-neutral-500">
              Status
              <select
                value={status}
                onChange={(e) => setStatus(e.target.value as TaskStatus)}
                className="mt-1 w-full rounded-lg border border-neutral-800 bg-neutral-950 px-2 py-1.5 text-sm text-neutral-100 outline-none focus:border-neutral-600"
              >
                {STATUSES.map((s) => (
                  <option key={s.key} value={s.key}>
                    {s.label}
                  </option>
                ))}
              </select>
            </label>

            {showDate && (
              <>
                <label className="flex-1 text-xs text-neutral-500">
                  Due date
                  <input
                    type="date"
                    value={dueDate}
                    onChange={(e) => setDueDate(e.target.value)}
                    className="mt-1 w-full rounded-lg border border-neutral-800 bg-neutral-950 px-2 py-1.5 text-sm text-neutral-100 outline-none focus:border-neutral-600"
                  />
                </label>

                <label className="flex-1 text-xs text-neutral-500">
                  Time
                  <input
                    type="time"
                    value={dueTime}
                    disabled={!dueDate}
                    onChange={(e) => setDueTime(e.target.value)}
                    className="mt-1 w-full rounded-lg border border-neutral-800 bg-neutral-950 px-2 py-1.5 text-sm text-neutral-100 outline-none focus:border-neutral-600 disabled:opacity-40"
                  />
                </label>
              </>
            )}
          </div>
        </div>

        {error && (
          <p className="mt-3 rounded-lg bg-red-500/10 px-3 py-2 text-xs text-red-400">
            {error}
          </p>
        )}

        <div className="mt-5 flex items-center justify-between">
          {isEditing && onDelete ? (
            <div className="flex items-center gap-2">
              <button
                onClick={handleDelete}
                className={`text-xs ${
                  confirmingDelete
                    ? "font-medium text-red-400"
                    : "text-neutral-500 hover:text-red-400"
                }`}
              >
                {confirmingDelete ? "Confirm delete" : "Delete task"}
              </button>
              {confirmingDelete && (
                <button
                  onClick={() => setConfirmingDelete(false)}
                  className="text-xs text-neutral-500 hover:text-neutral-300"
                >
                  Cancel
                </button>
              )}
            </div>
          ) : (
            <span />
          )}
          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="rounded-lg px-3 py-1.5 text-sm text-neutral-400 hover:bg-neutral-800"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={!title.trim() || saving}
              className="rounded-lg bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-500 disabled:opacity-40"
            >
              {isEditing ? "Save" : "Create"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
