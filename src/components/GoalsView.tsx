"use client";

import { useMemo } from "react";
import { EFFORT_LABELS, Goal, Task, isDefined } from "@/lib/supabase";

export default function GoalsView({
  goals,
  tasks,
  canEdit,
  onAddGoal,
  onOpenGoal,
  onOpenTask,
}: {
  goals: Goal[];
  tasks: Task[];
  canEdit: boolean;
  onAddGoal: () => void;
  onOpenGoal: (goal: Goal) => void;
  onOpenTask: (task: Task) => void;
}) {
  const byGoal = useMemo(() => {
    const map = new Map<string, Task[]>();
    for (const t of tasks) {
      if (!t.goal_id) continue;
      const list = map.get(t.goal_id) ?? [];
      list.push(t);
      map.set(t.goal_id, list);
    }
    return map;
  }, [tasks]);

  const orphans = useMemo(() => tasks.filter((t) => !t.goal_id), [tasks]);
  const undefinedTasks = useMemo(
    () => tasks.filter((t) => t.goal_id && !isDefined(t)),
    [tasks]
  );

  return (
    <div className="flex flex-col gap-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold text-ink">Goals</h2>
          <p className="text-xs text-ink-faint">
            Every task hangs off one of these. A goal with no movement is a goal
            you aren&apos;t working on.
          </p>
        </div>
        {canEdit && (
          <button
            onClick={onAddGoal}
            className="rounded-lg bg-ember px-3 py-1.5 text-sm font-medium text-on-ember hover:bg-ember-light"
          >
            + New goal
          </button>
        )}
      </div>

      {goals.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-line p-10 text-center text-sm text-ink-faint">
          No goals yet. Create one, then every task you add has somewhere to
          attach.
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {goals.map((goal) => (
            <GoalCard
              key={goal.id}
              goal={goal}
              tasks={byGoal.get(goal.id) ?? []}
              canEdit={canEdit}
              onOpenGoal={onOpenGoal}
              onOpenTask={onOpenTask}
            />
          ))}
        </div>
      )}

      {(orphans.length > 0 || undefinedTasks.length > 0) && (
        <div className="rounded-2xl border border-gold-deep/50 bg-gold-deep/10 p-4">
          <h3 className="text-sm font-medium text-gold">Needs defining</h3>
          <p className="mb-3 text-xs text-ink-faint">
            {orphans.length > 0 &&
              `${orphans.length} task${orphans.length === 1 ? "" : "s"} with no goal`}
            {orphans.length > 0 && undefinedTasks.length > 0 && " · "}
            {undefinedTasks.length > 0 &&
              `${undefinedTasks.length} missing an outcome, effort, or next action`}
            . Open each one to fill in the gaps.
          </p>
          <div className="flex flex-wrap gap-1.5">
            {[...orphans, ...undefinedTasks].map((t) => (
              <button
                key={t.id}
                onClick={() => onOpenTask(t)}
                className="rounded-lg bg-surf-high px-2 py-1 text-xs text-ink-dim hover:bg-surf-highest"
              >
                {t.title}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function GoalCard({
  goal,
  tasks,
  canEdit,
  onOpenGoal,
  onOpenTask,
}: {
  goal: Goal;
  tasks: Task[];
  canEdit: boolean;
  onOpenGoal: (goal: Goal) => void;
  onOpenTask: (task: Task) => void;
}) {
  const done = tasks.filter((t) => t.status === "done").length;
  const open = tasks.filter((t) => t.status !== "done");
  const pct = tasks.length ? Math.round((done / tasks.length) * 100) : 0;

  return (
    <div className="flex flex-col rounded-2xl border border-line bg-surf-low p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-ink">
            {goal.title}
          </h3>
          {goal.description && (
            <p className="mt-1 text-xs text-ink-faint">{goal.description}</p>
          )}
        </div>
        {canEdit && (
          <button
            onClick={() => onOpenGoal(goal)}
            className="shrink-0 text-xs text-ink-faint hover:text-ink"
          >
            Edit
          </button>
        )}
      </div>

      <div className="mt-3 flex items-center gap-2">
        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surf-high">
          <div
            className="h-full rounded-full bg-ember transition-all"
            style={{ width: `${pct}%` }}
          />
        </div>
        <span className="text-xs tabular-nums text-ink-faint">
          {done}/{tasks.length}
        </span>
      </div>

      {goal.target_date && (
        <p className="mt-2 text-[11px] text-ink-ghost">
          Target{" "}
          {new Date(`${goal.target_date}T00:00:00`).toLocaleDateString("en-US", {
            month: "short",
            day: "numeric",
            year: "numeric",
          })}
        </p>
      )}

      <div className="mt-3 flex flex-col gap-1">
        {open.length === 0 ? (
          <p className="text-xs text-ink-ghost">
            {tasks.length === 0
              ? "No tasks yet — nothing is moving this forward."
              : "All tasks done."}
          </p>
        ) : (
          open.slice(0, 4).map((t) => (
            <button
              key={t.id}
              onClick={() => onOpenTask(t)}
              className="flex items-baseline gap-2 rounded-lg px-2 py-1 text-left text-xs hover:bg-surf-high"
            >
              <span className="truncate text-ink-dim">{t.title}</span>
              {t.next_action && (
                <span className="truncate text-[11px] text-ink-ghost">
                  → {t.next_action}
                </span>
              )}
              {t.effort && (
                <span className="ml-auto shrink-0 text-[11px] text-ink-ghost">
                  {EFFORT_LABELS[t.effort]}
                </span>
              )}
            </button>
          ))
        )}
        {open.length > 4 && (
          <span className="px-2 text-[11px] text-ink-ghost">
            +{open.length - 4} more open
          </span>
        )}
      </div>
    </div>
  );
}
