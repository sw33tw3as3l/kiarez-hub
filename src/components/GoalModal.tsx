"use client";

import { useRef, useState } from "react";
import { Goal } from "@/lib/supabase";

export type GoalDraft = {
  title: string;
  description: string;
  target_date: string;
};

const inputClass =
  "w-full rounded-lg border border-line bg-canvas px-3 py-2 text-sm text-ink outline-none placeholder:text-ink-ghost focus:border-ember";

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
      className="fixed inset-0 z-50 flex items-center justify-center bg-canvas/85 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-2xl border border-line bg-surf p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-ink">
            {goal ? "Edit goal" : "New goal"}
          </h3>
          <button
            onClick={onClose}
            className="rounded p-1 text-ink-faint hover:bg-surf-high hover:text-ink-dim"
          >
            ✕
          </button>
        </div>

        <div className="flex flex-col gap-3">
          <label className="block text-xs text-ink-faint">
            <span className="mb-1 block">
              Goal<span className="ml-0.5 text-ember">*</span>
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

          <label className="block text-xs text-ink-faint">
            <span className="mb-1 block">Why it matters</span>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What changes for you once this is done?"
              rows={3}
              className={`resize-none ${inputClass}`}
            />
          </label>

          <label className="block text-xs text-ink-faint">
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
          <p className="mt-3 rounded-lg bg-danger-deep/25 px-3 py-2 text-xs text-danger">
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
                    ? "font-medium text-danger"
                    : "text-ink-faint hover:text-danger"
                }`}
              >
                {confirmingDelete ? "Confirm delete" : "Delete goal"}
              </button>
              {confirmingDelete ? (
                <button
                  onClick={() => setConfirmingDelete(false)}
                  className="text-xs text-ink-faint hover:text-ink-dim"
                >
                  Cancel
                </button>
              ) : (
                <span className="text-[11px] text-ink-ghost">
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
              className="rounded-lg px-3 py-1.5 text-sm text-ink-dim hover:bg-surf-high"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={!title.trim() || saving}
              className="rounded-lg bg-ember px-3 py-1.5 text-sm font-medium text-on-ember hover:bg-ember-light disabled:opacity-40"
            >
              {goal ? "Save" : "Create"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
