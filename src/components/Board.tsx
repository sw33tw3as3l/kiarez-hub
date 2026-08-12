"use client";

import { useEffect, useMemo, useState } from "react";
import { supabase, Goal, Task, TaskCategory, TaskStatus } from "@/lib/supabase";
import { addDays, fmtDate } from "@/lib/date";
import { randomFunLabel } from "@/lib/funLabels";
import KanbanBoard from "@/components/KanbanBoard";
import CalendarView from "@/components/CalendarView";
import GoalsView from "@/components/GoalsView";
import TaskModal, { TaskDraft } from "@/components/TaskModal";
import GoalModal, { GoalDraft } from "@/components/GoalModal";
import UnlockModal from "@/components/UnlockModal";

const EDIT_PIN = process.env.NEXT_PUBLIC_EDIT_PIN;

const VIEWS = [
  { key: "board", label: "Board" },
  { key: "calendar", label: "Calendar" },
  { key: "longterm", label: "Long-term" },
  { key: "goals", label: "Goals" },
] as const;

type View = (typeof VIEWS)[number]["key"];

type ModalState =
  | { mode: "create"; category: TaskCategory; status?: TaskStatus; date?: string }
  | { mode: "edit"; task: Task }
  | null;

type GoalModalState =
  | { mode: "create" }
  | { mode: "edit"; goal: Goal }
  | null;

function groupByStatus(items: Task[]) {
  const map: Record<TaskStatus, Task[]> = { todo: [], doing: [], done: [] };
  for (const t of items) map[t.status].push(t);
  return map;
}

function positionsFor(items: Task[], skipId?: string) {
  return Promise.all(
    items.map((t, i) => {
      if (t.id === skipId || t.position === i) return null;
      return supabase.from("tasks").update({ position: i }).eq("id", t.id);
    })
  );
}

export default function Board() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [goals, setGoals] = useState<Goal[]>([]);
  const [view, setView] = useState<View>("board");
  const [canEdit, setCanEdit] = useState(false);
  const [modal, setModal] = useState<ModalState>(null);
  const [goalModal, setGoalModal] = useState<GoalModalState>(null);
  const [unlocking, setUnlocking] = useState(false);
  const todayStr = fmtDate(new Date());
  const [selectedDay, setSelectedDay] = useState(todayStr);
  const [greeting, setGreeting] = useState("");

  useEffect(() => {
    // Runs once after mount so the server-prerendered greeting stays
    // stable and only randomizes client-side, avoiding a hydration mismatch.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setGreeting(randomFunLabel());
  }, []);

  useEffect(() => {
    const load = () => {
      supabase
        .from("tasks")
        .select("*")
        .order("position", { ascending: true })
        .then(({ data }) => setTasks(data ?? []));
      supabase
        .from("goals")
        .select("*")
        .order("position", { ascending: true })
        .then(({ data }) => setGoals(data ?? []));
    };

    load();

    let debounce: ReturnType<typeof setTimeout>;
    const debouncedLoad = () => {
      clearTimeout(debounce);
      debounce = setTimeout(load, 300);
    };

    const channel = supabase
      .channel("tasks-realtime")
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "tasks" },
        debouncedLoad
      )
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "goals" },
        debouncedLoad
      )
      .subscribe();

    return () => {
      clearTimeout(debounce);
      supabase.removeChannel(channel);
    };
  }, []);

  const goalTitles = useMemo(
    () => Object.fromEntries(goals.map((g) => [g.id, g.title])),
    [goals]
  );

  const dayTasksByStatus = useMemo(() => {
    return groupByStatus(
      tasks.filter(
        (t) =>
          t.category === "board" &&
          (t.due_date === selectedDay ||
            (!t.due_date && selectedDay === todayStr))
      )
    );
  }, [tasks, selectedDay, todayStr]);

  const longtermByStatus = useMemo(() => {
    return groupByStatus(tasks.filter((t) => t.category === "longterm"));
  }, [tasks]);

  const tasksByDate = useMemo(() => {
    const map: Record<string, Task[]> = {};
    for (const t of tasks) {
      if (!t.due_date || t.category !== "board") continue;
      (map[t.due_date] ??= []).push(t);
    }
    return map;
  }, [tasks]);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (view !== "board" || modal || goalModal || unlocking) return;
      const target = e.target as HTMLElement;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;

      if (e.key === "ArrowLeft") setSelectedDay((d) => addDays(d, -1));
      else if (e.key === "ArrowRight") setSelectedDay((d) => addDays(d, 1));
      else if (e.key === "t" || e.key === "T") setSelectedDay(todayStr);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [view, modal, goalModal, unlocking, todayStr]);

  function tryUnlock(pin: string) {
    if (EDIT_PIN && pin === EDIT_PIN) {
      setCanEdit(true);
      return true;
    }
    return false;
  }

  /** Resolves the draft's goal, creating one first if the user typed a new name. */
  async function resolveGoalId(draft: TaskDraft) {
    if (!draft.newGoalTitle) return draft.goal_id || null;
    const { data, error } = await supabase
      .from("goals")
      .insert({ title: draft.newGoalTitle, position: goals.length })
      .select()
      .single();
    if (error) throw error;
    setGoals((prev) => [...prev, data as Goal]);
    return (data as Goal).id;
  }

  async function handleSave(draft: TaskDraft) {
    const goalId = await resolveGoalId(draft);
    const isBoard = draft.category === "board";

    const fields = {
      title: draft.title,
      description: draft.description || null,
      status: draft.status,
      category: draft.category,
      due_date: isBoard ? draft.due_date || null : null,
      due_time: isBoard ? draft.due_time || null : null,
      goal_id: goalId,
      outcome: draft.outcome,
      effort: draft.effort,
      next_action: draft.next_action,
    };

    if (modal?.mode === "edit") {
      const { error } = await supabase
        .from("tasks")
        .update(fields)
        .eq("id", modal.task.id);
      if (error) throw error;
    } else if (modal?.mode === "create") {
      const subset =
        draft.category === "longterm" ? longtermByStatus : dayTasksByStatus;
      const position = subset[draft.status]?.length ?? 0;
      const { error } = await supabase
        .from("tasks")
        .insert({ ...fields, position });
      if (error) throw error;
    }
  }

  async function handleDelete() {
    if (modal?.mode !== "edit") return;
    const { error } = await supabase
      .from("tasks")
      .delete()
      .eq("id", modal.task.id);
    if (error) throw error;
  }

  async function handleGoalSave(draft: GoalDraft) {
    const fields = {
      title: draft.title,
      description: draft.description || null,
      target_date: draft.target_date || null,
    };
    if (goalModal?.mode === "edit") {
      const { error } = await supabase
        .from("goals")
        .update(fields)
        .eq("id", goalModal.goal.id);
      if (error) throw error;
    } else {
      const { error } = await supabase
        .from("goals")
        .insert({ ...fields, position: goals.length });
      if (error) throw error;
    }
  }

  async function handleGoalDelete() {
    if (goalModal?.mode !== "edit") return;
    const { error } = await supabase
      .from("goals")
      .delete()
      .eq("id", goalModal.goal.id);
    if (error) throw error;
  }

  async function deleteTaskDirect(task: Task) {
    const { error } = await supabase.from("tasks").delete().eq("id", task.id);
    if (error) console.error(error);
  }

  async function persistCardMove(
    subset: Record<TaskStatus, Task[]>,
    taskId: string,
    newStatus: TaskStatus,
    newIndex: number
  ) {
    const moved = tasks.find((t) => t.id === taskId);
    if (!moved) return;
    const sourceStatus = moved.status;

    setTasks((prev) =>
      prev.map((t) => (t.id === taskId ? { ...t, status: newStatus } : t))
    );

    const destItems = subset[newStatus].filter((t) => t.id !== taskId);
    destItems.splice(newIndex, 0, { ...moved, status: newStatus });

    try {
      await supabase
        .from("tasks")
        .update({ status: newStatus, position: newIndex })
        .eq("id", taskId);

      const writes = [positionsFor(destItems, taskId)];
      if (sourceStatus !== newStatus) {
        writes.push(
          positionsFor(subset[sourceStatus].filter((t) => t.id !== taskId))
        );
      }
      await Promise.all(writes);
    } catch (err) {
      console.error(err);
    }
  }

  return (
    // No background color here: the wallpaper backdrop lives on body::before,
    // and an opaque root element would cover it.
    <div className="min-h-screen text-ink">
      <header className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 border-b border-line bg-canvas/50 px-4 py-3 backdrop-blur-md sm:px-6">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-ember text-sm font-bold text-on-ember">
            K
          </div>
          <div className="leading-tight">
            <h1 className="text-sm font-semibold tracking-tight">KiaRez Hub</h1>
            <p className="hidden text-xs text-ink-faint sm:block">
              {greeting || "Personal tasks & calendar"}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div className="flex rounded-lg border border-line p-0.5 text-sm">
            {VIEWS.map((v) => (
              <button
                key={v.key}
                onClick={() => setView(v.key)}
                className={`rounded-md px-3 py-1.5 transition ${
                  view === v.key
                    ? "bg-ember font-medium text-on-ember"
                    : "text-ink-dim hover:text-ink"
                }`}
              >
                {v.label}
              </button>
            ))}
          </div>

          {canEdit ? (
            <span className="whitespace-nowrap text-xs font-medium text-ember">
              Editing
            </span>
          ) : (
            <button
              onClick={() => setUnlocking(true)}
              className="whitespace-nowrap text-xs text-ink-dim underline hover:text-ink"
            >
              Edit
            </button>
          )}
        </div>
      </header>

      <div className="mx-auto max-w-6xl">
        {view === "board" && (
          <>
            <div className="flex items-center justify-center gap-3 px-6 pt-6 pb-4">
              <button
                onClick={() => setSelectedDay((d) => addDays(d, -1))}
                className="rounded-lg px-2 py-1.5 text-ink-dim hover:bg-surf-high"
              >
                ←
              </button>
              <h2
                className={`w-56 text-center text-sm font-semibold ${
                  selectedDay === todayStr
                    ? "rounded-full bg-ember-deep/35 py-1 text-ember"
                    : "text-ink"
                }`}
              >
                {new Date(`${selectedDay}T00:00:00`).toLocaleDateString(
                  "en-US",
                  {
                    weekday: "long",
                    month: "long",
                    day: "numeric",
                  }
                )}
              </h2>
              <button
                onClick={() => setSelectedDay((d) => addDays(d, 1))}
                className="rounded-lg px-2 py-1.5 text-ink-dim hover:bg-surf-high"
              >
                →
              </button>
            </div>
            <KanbanBoard
              tasksByStatus={dayTasksByStatus}
              goalTitles={goalTitles}
              canEdit={canEdit}
              onAdd={(status) =>
                setModal({
                  mode: "create",
                  category: "board",
                  status,
                  date: selectedDay,
                })
              }
              onOpen={(task) => canEdit && setModal({ mode: "edit", task })}
              onDelete={deleteTaskDirect}
              onCardMove={(id, status, idx) =>
                persistCardMove(dayTasksByStatus, id, status, idx)
              }
            />
          </>
        )}

        {view === "calendar" && (
          <CalendarView
            tasksByDate={tasksByDate}
            canEdit={canEdit}
            onAdd={(date) =>
              setModal({ mode: "create", category: "board", date })
            }
            onOpen={(task) => canEdit && setModal({ mode: "edit", task })}
          />
        )}

        {view === "longterm" && (
          <div className="pt-6">
            <KanbanBoard
              tasksByStatus={longtermByStatus}
              goalTitles={goalTitles}
              canEdit={canEdit}
              onAdd={(status) =>
                setModal({ mode: "create", category: "longterm", status })
              }
              onOpen={(task) => canEdit && setModal({ mode: "edit", task })}
              onDelete={deleteTaskDirect}
              onCardMove={(id, status, idx) =>
                persistCardMove(longtermByStatus, id, status, idx)
              }
            />
          </div>
        )}

        {view === "goals" && (
          <GoalsView
            goals={goals}
            tasks={tasks}
            canEdit={canEdit}
            onAddGoal={() => setGoalModal({ mode: "create" })}
            onOpenGoal={(goal) => canEdit && setGoalModal({ mode: "edit", goal })}
            onOpenTask={(task) => canEdit && setModal({ mode: "edit", task })}
          />
        )}
      </div>

      {modal && (
        <TaskModal
          task={modal.mode === "edit" ? modal.task : null}
          category={modal.mode === "edit" ? modal.task.category : modal.category}
          initialStatus={modal.mode === "create" ? modal.status : undefined}
          initialDate={modal.mode === "create" ? modal.date : undefined}
          goals={goals}
          onClose={() => setModal(null)}
          onSave={handleSave}
          onDelete={modal.mode === "edit" ? handleDelete : undefined}
        />
      )}

      {goalModal && (
        <GoalModal
          goal={goalModal.mode === "edit" ? goalModal.goal : null}
          onClose={() => setGoalModal(null)}
          onSave={handleGoalSave}
          onDelete={goalModal.mode === "edit" ? handleGoalDelete : undefined}
        />
      )}

      {unlocking && (
        <UnlockModal onClose={() => setUnlocking(false)} onUnlock={tryUnlock} />
      )}
    </div>
  );
}
