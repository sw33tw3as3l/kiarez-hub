"use client";

import { useEffect, useMemo, useState } from "react";
import { supabase, Task, TaskStatus } from "@/lib/supabase";
import { addDays, fmtDate } from "@/lib/date";
import KanbanBoard from "@/components/KanbanBoard";
import CalendarView from "@/components/CalendarView";
import TaskModal, { TaskDraft } from "@/components/TaskModal";
import UnlockModal from "@/components/UnlockModal";

const EDIT_PIN = process.env.NEXT_PUBLIC_EDIT_PIN;

type ModalState =
  | { mode: "create"; status?: TaskStatus; date?: string }
  | { mode: "edit"; task: Task }
  | null;

export default function Board() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [view, setView] = useState<"board" | "calendar">("board");
  const [canEdit, setCanEdit] = useState(false);
  const [modal, setModal] = useState<ModalState>(null);
  const [unlocking, setUnlocking] = useState(false);
  const todayStr = fmtDate(new Date());
  const [selectedDay, setSelectedDay] = useState(todayStr);

  useEffect(() => {
    const load = () =>
      supabase
        .from("tasks")
        .select("*")
        .order("position", { ascending: true })
        .then(({ data }) => setTasks(data ?? []));

    load();

    const channel = supabase
      .channel("tasks-realtime")
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "tasks" },
        load
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

  const dayTasksByStatus = useMemo(() => {
    const map: Record<TaskStatus, Task[]> = { todo: [], doing: [], done: [] };
    for (const t of tasks) {
      const belongsToDay =
        t.due_date === selectedDay || (!t.due_date && selectedDay === todayStr);
      if (belongsToDay) map[t.status].push(t);
    }
    return map;
  }, [tasks, selectedDay, todayStr]);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (view !== "board" || modal || unlocking) return;
      const target = e.target as HTMLElement;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;

      if (e.key === "ArrowLeft") setSelectedDay((d) => addDays(d, -1));
      else if (e.key === "ArrowRight") setSelectedDay((d) => addDays(d, 1));
      else if (e.key === "t" || e.key === "T") setSelectedDay(todayStr);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [view, modal, unlocking, todayStr]);

  const tasksByDate = useMemo(() => {
    const map: Record<string, Task[]> = {};
    for (const t of tasks) {
      if (!t.due_date) continue;
      (map[t.due_date] ??= []).push(t);
    }
    return map;
  }, [tasks]);

  function tryUnlock(pin: string) {
    if (EDIT_PIN && pin === EDIT_PIN) {
      setCanEdit(true);
      return true;
    }
    return false;
  }

  async function handleSave(draft: TaskDraft) {
    if (modal?.mode === "edit") {
      const { error } = await supabase
        .from("tasks")
        .update({
          title: draft.title,
          description: draft.description || null,
          status: draft.status,
          due_date: draft.due_date || null,
          due_time: draft.due_time || null,
        })
        .eq("id", modal.task.id);
      if (error) throw error;
    } else {
      const status = draft.status;
      const position = tasksByStatus[status]?.length ?? 0;
      const { error } = await supabase.from("tasks").insert({
        title: draft.title,
        description: draft.description || null,
        status,
        due_date: draft.due_date || null,
        due_time: draft.due_time || null,
        position,
      });
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

  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-100">
      <header className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 border-b border-neutral-800 px-4 py-3 sm:px-6">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-blue-600 text-sm font-bold text-white">
            K
          </div>
          <div className="leading-tight">
            <h1 className="text-sm font-semibold tracking-tight">
              KiaRez Hub
            </h1>
            <p className="hidden text-xs text-neutral-500 sm:block">
              Personal tasks &amp; calendar
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div className="flex rounded-lg border border-neutral-800 p-0.5 text-sm">
            <button
              onClick={() => setView("board")}
              className={`rounded-md px-3 py-1.5 transition ${
                view === "board"
                  ? "bg-neutral-800 text-neutral-100"
                  : "text-neutral-400 hover:text-neutral-200"
              }`}
            >
              Board
            </button>
            <button
              onClick={() => setView("calendar")}
              className={`rounded-md px-3 py-1.5 transition ${
                view === "calendar"
                  ? "bg-neutral-800 text-neutral-100"
                  : "text-neutral-400 hover:text-neutral-200"
              }`}
            >
              Calendar
            </button>
          </div>

          {canEdit && (
            <button
              onClick={() => setModal({ mode: "create" })}
              className="whitespace-nowrap rounded-lg bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-500"
            >
              + New Task
            </button>
          )}
          {canEdit ? (
            <span className="whitespace-nowrap text-xs font-medium text-emerald-400">
              Editing
            </span>
          ) : (
            <button
              onClick={() => setUnlocking(true)}
              className="whitespace-nowrap text-xs text-neutral-400 underline hover:text-neutral-200"
            >
              Edit
            </button>
          )}
        </div>
      </header>

      <div className="mx-auto max-w-6xl">
        {view === "board" ? (
          <>
            <div className="flex items-center justify-center gap-3 px-6 pt-6 pb-4">
              <button
                onClick={() => setSelectedDay((d) => addDays(d, -1))}
                className="rounded-lg px-2 py-1.5 text-neutral-400 hover:bg-neutral-800"
              >
                ←
              </button>
              <button
                onClick={() => setSelectedDay(todayStr)}
                className="rounded-lg border border-neutral-800 px-3 py-1.5 text-sm text-neutral-300 hover:bg-neutral-800"
              >
                Today
              </button>
              <h2 className="w-56 text-center text-sm font-semibold text-neutral-100">
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
                className="rounded-lg px-2 py-1.5 text-neutral-400 hover:bg-neutral-800"
              >
                →
              </button>
            </div>
            <KanbanBoard
              tasksByStatus={dayTasksByStatus}
              canEdit={canEdit}
              onAdd={(status) =>
                setModal({ mode: "create", status, date: selectedDay })
              }
              onOpen={(task) => canEdit && setModal({ mode: "edit", task })}
            />
          </>
        ) : (
          <CalendarView
            tasksByDate={tasksByDate}
            canEdit={canEdit}
            onAdd={(date) => setModal({ mode: "create", date })}
            onOpen={(task) => canEdit && setModal({ mode: "edit", task })}
          />
        )}
      </div>

      {modal && (
        <TaskModal
          task={modal.mode === "edit" ? modal.task : null}
          initialStatus={modal.mode === "create" ? modal.status : undefined}
          initialDate={modal.mode === "create" ? modal.date : undefined}
          onClose={() => setModal(null)}
          onSave={handleSave}
          onDelete={modal.mode === "edit" ? handleDelete : undefined}
        />
      )}

      {unlocking && (
        <UnlockModal onClose={() => setUnlocking(false)} onUnlock={tryUnlock} />
      )}
    </div>
  );
}
