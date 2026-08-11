"use client";

import { useRef, useState, type ReactNode } from "react";
import {
  EFFORTS,
  Goal,
  STATUSES,
  Task,
  TaskCategory,
  TaskEffort,
  TaskStatus,
  isOversized,
} from "@/lib/supabase";

export type TaskDraft = {
  title: string;
  description: string;
  status: TaskStatus;
  category: TaskCategory;
  due_date: string;
  due_time: string;
  goal_id: string;
  /** Set when the user typed a brand new goal instead of picking one. */
  newGoalTitle: string;
  outcome: string;
  effort: TaskEffort;
  next_action: string;
};

const NEW_GOAL = "__new__";

const inputClass =
  "w-full rounded-lg border border-neutral-800 bg-neutral-950 px-3 py-2 text-sm text-neutral-100 outline-none placeholder:text-neutral-600 focus:border-red-600";

export default function TaskModal({
  task,
  category: initialCategory,
  initialStatus,
  initialDate,
  goals,
  onClose,
  onSave,
  onDelete,
}: {
  task: Task | null;
  category: TaskCategory;
  initialStatus?: TaskStatus;
  initialDate?: string;
  goals: Goal[];
  onClose: () => void;
  onSave: (draft: TaskDraft) => Promise<void>;
  onDelete?: () => Promise<void>;
}) {
  const [step, setStep] = useState<1 | 2>(1);
  const [title, setTitle] = useState(task?.title ?? "");
  const [description, setDescription] = useState(task?.description ?? "");
  const [status, setStatus] = useState<TaskStatus>(
    task?.status ?? initialStatus ?? "todo"
  );
  const [category, setCategory] = useState<TaskCategory>(
    task?.category ?? initialCategory
  );
  const [dueDate, setDueDate] = useState(task?.due_date ?? initialDate ?? "");
  const [dueTime, setDueTime] = useState(task?.due_time?.slice(0, 5) ?? "");
  const [goalId, setGoalId] = useState(task?.goal_id ?? "");
  const [newGoalTitle, setNewGoalTitle] = useState("");
  const [outcome, setOutcome] = useState(task?.outcome ?? "");
  const [effort, setEffort] = useState<TaskEffort | "">(task?.effort ?? "");
  const [nextAction, setNextAction] = useState(task?.next_action ?? "");
  const [saving, setSaving] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [error, setError] = useState("");

  const isEditing = !!task;
  const submitting = useRef(false);
  const showDate = category === "board";
  const addingGoal = goalId === NEW_GOAL;

  const hasGoal = addingGoal ? !!newGoalTitle.trim() : !!goalId;
  const step1Valid = !!title.trim() && hasGoal && !!outcome.trim();
  // Half-day-or-bigger work doesn't belong on a single day's board — split it
  // into smaller tasks or move it to Long-term before it can be saved.
  const tooBigForBoard = category === "board" && isOversized(effort);
  const step2Valid = !!effort && !!nextAction.trim() && !tooBigForBoard;

  async function handleSave() {
    if (!step1Valid || !step2Valid || !effort || submitting.current) return;
    submitting.current = true;
    setSaving(true);
    setError("");
    try {
      await onSave({
        title: title.trim(),
        description: description.trim(),
        status,
        category,
        due_date: showDate ? dueDate : "",
        due_time: showDate && dueDate ? dueTime : "",
        goal_id: addingGoal ? "" : goalId,
        newGoalTitle: addingGoal ? newGoalTitle.trim() : "",
        outcome: outcome.trim(),
        effort,
        next_action: nextAction.trim(),
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
        className="max-h-[90vh] w-full max-w-md overflow-y-auto rounded-2xl border border-neutral-800 bg-neutral-900 p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-1 flex items-center justify-between">
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

        <div className="mb-4 flex items-center gap-2 text-xs">
          <StepPip active={step === 1} done={step > 1} label="Why & what" />
          <span className="h-px flex-1 bg-neutral-800" />
          <StepPip active={step === 2} done={false} label="Size & first step" />
        </div>

        {step === 1 ? (
          <div className="flex flex-col gap-3">
            <Field label="Title" required>
              <input
                autoFocus
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="What is the task?"
                className={inputClass}
              />
            </Field>

            <Field
              label="Goal it serves"
              required
              hint="A task with no goal is either a goal itself, or noise."
            >
              <select
                value={goalId}
                onChange={(e) => setGoalId(e.target.value)}
                className={inputClass}
              >
                <option value="">Pick a goal…</option>
                {goals.map((g) => (
                  <option key={g.id} value={g.id}>
                    {g.title}
                  </option>
                ))}
                <option value={NEW_GOAL}>+ New goal…</option>
              </select>
              {addingGoal && (
                <input
                  value={newGoalTitle}
                  onChange={(e) => setNewGoalTitle(e.target.value)}
                  placeholder="Name the new goal"
                  className={`mt-2 ${inputClass}`}
                />
              )}
            </Field>

            <Field
              label="Definition of done"
              required
              hint="A sentence you can check. If you can't write it, it isn't a task yet."
            >
              <textarea
                value={outcome}
                onChange={(e) => setOutcome(e.target.value)}
                placeholder="Done when… e.g. landing page loads under 1s on mobile"
                rows={2}
                className={`resize-none ${inputClass}`}
              />
            </Field>

            <Field label="Notes" hint="Optional context.">
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Anything else worth remembering"
                rows={2}
                className={`resize-none ${inputClass}`}
              />
            </Field>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            <Field label="Where it lives" required plain>
              <div className="flex rounded-lg border border-neutral-800 p-0.5 text-sm">
                {(
                  [
                    { key: "board", label: "A day" },
                    { key: "longterm", label: "Long-term" },
                  ] as const
                ).map((c) => (
                  <button
                    key={c.key}
                    onClick={() => setCategory(c.key)}
                    className={`flex-1 rounded-md px-3 py-1.5 transition ${
                      category === c.key
                        ? "bg-red-600 font-medium text-white"
                        : "text-neutral-400 hover:text-neutral-200"
                    }`}
                  >
                    {c.label}
                  </button>
                ))}
              </div>
            </Field>

            <Field
              label="Effort"
              required
              plain
              hint="Half a day or more can't sit on a day board — split it or move it to Long-term."
            >
              <div className="grid grid-cols-3 gap-1.5">
                {EFFORTS.map((e) => (
                  <button
                    key={e.key}
                    onClick={() => setEffort(e.key)}
                    className={`rounded-lg border px-2 py-1.5 text-xs transition ${
                      effort === e.key
                        ? "border-red-600 bg-red-600/20 font-medium text-red-300"
                        : "border-neutral-800 text-neutral-400 hover:border-neutral-700 hover:text-neutral-200"
                    }`}
                  >
                    {e.label}
                  </button>
                ))}
              </div>
            </Field>

            {tooBigForBoard && (
              <div className="rounded-lg border border-red-600/40 bg-red-600/10 px-3 py-2 text-xs text-red-300">
                That&apos;s too big for a single day. Split it into smaller
                tasks, or{" "}
                <button
                  onClick={() => setCategory("longterm")}
                  className="font-medium underline underline-offset-2 hover:text-red-200"
                >
                  move it to Long-term
                </button>
                .
              </div>
            )}

            <Field
              label="Next action"
              required
              hint="The first physical step. Undefined first steps are what stall tasks."
            >
              <input
                value={nextAction}
                onChange={(e) => setNextAction(e.target.value)}
                placeholder="e.g. Open Lighthouse and record the baseline"
                className={inputClass}
                onKeyDown={(e) =>
                  e.key === "Enter" && step2Valid && handleSave()
                }
              />
            </Field>

            <div className="flex gap-2">
              <Field label="Status" className="flex-1">
                <select
                  value={status}
                  onChange={(e) => setStatus(e.target.value as TaskStatus)}
                  className={inputClass}
                >
                  {STATUSES.map((s) => (
                    <option key={s.key} value={s.key}>
                      {s.label}
                    </option>
                  ))}
                </select>
              </Field>

              {showDate && (
                <>
                  <Field label="Due date" className="flex-1">
                    <input
                      type="date"
                      value={dueDate}
                      onChange={(e) => setDueDate(e.target.value)}
                      className={inputClass}
                    />
                  </Field>
                  <Field label="Time" className="flex-1">
                    <input
                      type="time"
                      value={dueTime}
                      disabled={!dueDate}
                      onChange={(e) => setDueTime(e.target.value)}
                      className={`disabled:opacity-40 ${inputClass}`}
                    />
                  </Field>
                </>
              )}
            </div>
          </div>
        )}

        {error && (
          <p className="mt-3 rounded-lg bg-red-500/10 px-3 py-2 text-xs text-red-400">
            {error}
          </p>
        )}

        <div className="mt-5 flex items-center justify-between gap-3">
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
            {step === 1 ? (
              <>
                <button
                  onClick={onClose}
                  className="rounded-lg px-3 py-1.5 text-sm text-neutral-400 hover:bg-neutral-800"
                >
                  Cancel
                </button>
                <button
                  onClick={() => setStep(2)}
                  disabled={!step1Valid}
                  className="rounded-lg bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-500 disabled:opacity-40"
                >
                  Next →
                </button>
              </>
            ) : (
              <>
                <button
                  onClick={() => setStep(1)}
                  className="rounded-lg px-3 py-1.5 text-sm text-neutral-400 hover:bg-neutral-800"
                >
                  ← Back
                </button>
                <button
                  onClick={handleSave}
                  disabled={!step1Valid || !step2Valid || saving}
                  className="rounded-lg bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-500 disabled:opacity-40"
                >
                  {isEditing ? "Save" : "Create"}
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function StepPip({
  active,
  done,
  label,
}: {
  active: boolean;
  done: boolean;
  label: string;
}) {
  return (
    <span
      className={`whitespace-nowrap ${
        active ? "font-medium text-red-400" : done ? "text-neutral-400" : "text-neutral-600"
      }`}
    >
      {label}
    </span>
  );
}

function Field({
  label,
  required,
  hint,
  className,
  plain,
  children,
}: {
  label: string;
  required?: boolean;
  hint?: string;
  className?: string;
  /** Render as a div instead of a label — for fields made of buttons. */
  plain?: boolean;
  children: ReactNode;
}) {
  const Tag = plain ? "div" : "label";
  return (
    <Tag className={`block text-xs text-neutral-500 ${className ?? ""}`}>
      <span className="mb-1 block">
        {label}
        {required && <span className="ml-0.5 text-red-500">*</span>}
      </span>
      {children}
      {hint && <span className="mt-1 block text-[11px] text-neutral-600">{hint}</span>}
    </Tag>
  );
}
