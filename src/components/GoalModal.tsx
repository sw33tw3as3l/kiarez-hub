"use client";

import { useRef, useState } from "react";
import { Goal } from "@/lib/supabase";

export type GoalDraft = {
  title: string;
  description: string;
  target_date: string;
};

const inputClass =
  "w-full rounded-lg border border-neutral-800 bg-neutral-950 px-3 py-2 text-sm text-neutral-100 outline-none placeholder:text-neutral-600 focus:border-red-600";

export default function GoalModal({
  goal,
  onClose,
  onSave,
  onDelete,
}: {
  goal: Goal | null;
  onClose: () => void;
  onSave: (draft: GoalDraft) => Promise<void>;
  onDelete?: () => Promise<void>;
}) {
  const [title, setTitle] = useState(goal?.title ?? "");
  const [description, setDescription] = useState(goal?.description ?? "");
  const [targetDate, setTargetDate] = useState(goal?.target_date ?? "");
  const [saving, setSaving] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [error, setError] = useState("");

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
        target_date: targetDate,
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
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-2xl border border-neutral-800 bg-neutral-900 p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-neutral-200">
            {goal ? "Edit goal" : "New goal"}
          </h3>
          <button
            onClick={onClose}
            className="rounded p-1 text-neutral-500 hover:bg-neutral-800 hover:text-neutral-300"
          >
            ✕
          </button>
        </div>

        <div className="flex flex-col gap-3">
          <label className="block text-xs text-neutral-500">
            <span className="mb-1 block">
              Goal<span className="ml-0.5 text-red-500">*</span>
            </span>
            <input
              autoFocus
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Ship the portfolio site"
              className={inputClass}
              onKeyDown={(e) => e.key === "Enter" && handleSave()}
            />
          </label>

          <label className="block text-xs text-neutral-500">
            <span className="mb-1 block">Why it matters</span>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What changes for you once this is done?"
              rows={3}
              className={`resize-none ${inputClass}`}
            />
          </label>

          <label className="block text-xs text-neutral-500">
            <span className="mb-1 block">Target date</span>
            <input
              type="date"
              value={targetDate}
              onChange={(e) => setTargetDate(e.target.value)}
              className={inputClass}
            />
          </label>
        </div>

        {error && (
          <p className="mt-3 rounded-lg bg-red-500/10 px-3 py-2 text-xs text-red-400">
            {error}
          </p>
        )}

        <div className="mt-5 flex items-center justify-between">
          {goal && onDelete ? (
            <div className="flex items-center gap-2">
              <button
                onClick={handleDelete}
                className={`text-xs ${
                  confirmingDelete
                    ? "font-medium text-red-400"
                    : "text-neutral-500 hover:text-red-400"
                }`}
              >
                {confirmingDelete ? "Confirm delete" : "Delete goal"}
              </button>
              {confirmingDelete ? (
                <button
                  onClick={() => setConfirmingDelete(false)}
                  className="text-xs text-neutral-500 hover:text-neutral-300"
                >
                  Cancel
                </button>
              ) : (
                <span className="text-[11px] text-neutral-600">
                  Its tasks stay, unlinked
                </span>
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
              className="rounded-lg bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-500 disabled:opacity-40"
            >
              {goal ? "Save" : "Create"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
