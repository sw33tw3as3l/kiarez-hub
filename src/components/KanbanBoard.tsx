"use client";

import { useState } from "react";
import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  closestCorners,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import {
  EFFORT_LABELS,
  STATUSES,
  STATUS_COLORS,
  Task,
  TaskStatus,
  isDefined,
} from "@/lib/supabase";

const columnDropId = (status: TaskStatus) => `column-${status}`;

export default function KanbanBoard({
  tasksByStatus,
  goalTitles,
  canEdit,
  onAdd,
  onOpen,
  onDelete,
  onCardMove,
}: {
  tasksByStatus: Record<TaskStatus, Task[]>;
  goalTitles: Record<string, string>;
  canEdit: boolean;
  onAdd: (status: TaskStatus) => void;
  onOpen: (task: Task) => void;
  onDelete: (task: Task) => void;
  onCardMove: (taskId: string, newStatus: TaskStatus, newIndex: number) => void;
}) {
  const [activeTask, setActiveTask] = useState<Task | null>(null);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );

  const taskById = new Map(
    STATUSES.flatMap((c) => tasksByStatus[c.key]).map((t) => [t.id, t])
  );

  function statusOf(overId: string): TaskStatus | null {
    const prefixed = STATUSES.find((c) => columnDropId(c.key) === overId);
    if (prefixed) return prefixed.key;
    return taskById.get(overId)?.status ?? null;
  }

  function handleDragStart(event: DragStartEvent) {
    setActiveTask(taskById.get(String(event.active.id)) ?? null);
  }

  function handleDragEnd(event: DragEndEvent) {
    setActiveTask(null);
    const { active, over } = event;
    if (!over) return;

    const activeId = String(active.id);
    const overId = String(over.id);
    const destStatus = statusOf(overId);
    if (!destStatus) return;

    const destItems = tasksByStatus[destStatus];
    const overIsColumn = overId === columnDropId(destStatus);
    const newIndex = overIsColumn
      ? destItems.length
      : destItems.findIndex((t) => t.id === overId);

    const sourceStatus = taskById.get(activeId)?.status;
    if (sourceStatus === destStatus) {
      const oldIndex = destItems.findIndex((t) => t.id === activeId);
      if (oldIndex === -1 || oldIndex === newIndex) return;
    }

    onCardMove(activeId, destStatus, newIndex);
  }

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCorners}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
    >
      <div className="grid grid-cols-1 gap-4 p-6 md:grid-cols-3">
        {STATUSES.map((col) => (
          <Column
            key={col.key}
            status={col.key}
            label={col.label}
            tasks={tasksByStatus[col.key]}
            goalTitles={goalTitles}
            canEdit={canEdit}
            onAdd={onAdd}
            onOpen={onOpen}
            onDelete={onDelete}
          />
        ))}
      </div>

      <DragOverlay>
        {activeTask && (
          <Card task={activeTask} goalTitles={goalTitles} canEdit={false} />
        )}
      </DragOverlay>
    </DndContext>
  );
}

function Column({
  status,
  label,
  tasks,
  goalTitles,
  canEdit,
  onAdd,
  onOpen,
  onDelete,
}: {
  status: TaskStatus;
  label: string;
  tasks: Task[];
  goalTitles: Record<string, string>;
  canEdit: boolean;
  onAdd: (status: TaskStatus) => void;
  onOpen: (task: Task) => void;
  onDelete: (task: Task) => void;
}) {
  const { setNodeRef } = useDroppable({ id: columnDropId(status) });

  return (
    <div className="rounded-2xl bg-neutral-900/60 p-3">
      <div className="mb-3 flex items-center justify-between px-1">
        <div className="flex items-center gap-2">
          <span
            className={`h-2 w-2 rounded-full ${STATUS_COLORS[status].dot}`}
          />
          <h2 className="text-sm font-medium text-neutral-300">{label}</h2>
        </div>
        <span className="text-xs text-neutral-500">{tasks.length}</span>
      </div>

      <SortableContext
        items={tasks.map((t) => t.id)}
        strategy={verticalListSortingStrategy}
      >
        <div ref={setNodeRef} className="flex min-h-[60px] flex-col gap-2">
          {tasks.map((task) => (
            <SortableCard
              key={task.id}
              task={task}
              goalTitles={goalTitles}
              canEdit={canEdit}
              onOpen={onOpen}
              onDelete={onDelete}
            />
          ))}

          {canEdit && (
            <button
              onClick={() => onAdd(status)}
              className="rounded-xl border border-dashed border-neutral-800 py-2 text-xs text-neutral-500 transition hover:border-neutral-700 hover:text-neutral-300"
            >
              + New task
            </button>
          )}
        </div>
      </SortableContext>
    </div>
  );
}

function SortableCard({
  task,
  goalTitles,
  canEdit,
  onOpen,
  onDelete,
}: {
  task: Task;
  goalTitles: Record<string, string>;
  canEdit: boolean;
  onOpen: (task: Task) => void;
  onDelete: (task: Task) => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: task.id, disabled: !canEdit });
  const [expanded, setExpanded] = useState(false);

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      {...(canEdit ? attributes : {})}
      {...(canEdit ? listeners : {})}
      onClick={() => (canEdit ? onOpen(task) : setExpanded((e) => !e))}
      className={`touch-none ${isDragging ? "opacity-40" : ""}`}
    >
      <Card
        task={task}
        goalTitles={goalTitles}
        canEdit={canEdit}
        onDelete={onDelete}
        expanded={expanded}
      />
    </div>
  );
}

function Card({
  task,
  goalTitles,
  canEdit,
  onDelete,
  expanded,
}: {
  task: Task;
  goalTitles: Record<string, string>;
  canEdit: boolean;
  onDelete?: (task: Task) => void;
  expanded?: boolean;
}) {
  const goalTitle = task.goal_id ? goalTitles[task.goal_id] : null;
  const needsDefining = !isDefined(task);

  return (
    <div
      className={`group relative cursor-pointer rounded-xl border bg-neutral-900 p-3 text-left text-sm shadow-sm transition hover:bg-neutral-800 ${
        needsDefining
          ? "border-red-600/50 hover:border-red-600"
          : "border-neutral-800 hover:border-neutral-700"
      }`}
    >
      <div className="mb-1 flex items-center gap-1.5 pr-5 text-[11px]">
        {goalTitle ? (
          <span className="truncate rounded bg-neutral-800 px-1.5 py-0.5 text-neutral-400">
            {goalTitle}
          </span>
        ) : (
          <span className="shrink-0 rounded bg-red-600/20 px-1.5 py-0.5 font-medium text-red-400">
            No goal
          </span>
        )}
        {task.effort && (
          <span className="ml-auto shrink-0 text-neutral-600">
            {EFFORT_LABELS[task.effort]}
          </span>
        )}
      </div>

      <div
        className={
          task.status === "done"
            ? "pr-5 text-neutral-400 line-through decoration-neutral-600"
            : "pr-5 text-neutral-100"
        }
      >
        {task.title}
      </div>

      {/* The next action is what you actually do, so it outranks the notes. */}
      {task.next_action ? (
        <div className="mt-1 truncate pr-5 text-xs text-neutral-500">
          → {task.next_action}
        </div>
      ) : (
        <div className="mt-1 pr-5 text-xs text-red-400/80">
          → no next step defined
        </div>
      )}

      {expanded && (
        <div className="mt-2 flex flex-col gap-1 border-t border-neutral-800 pt-2 text-xs text-neutral-500">
          {task.outcome && (
            <p className="whitespace-pre-wrap">
              <span className="text-neutral-600">Done when: </span>
              {task.outcome}
            </p>
          )}
          {task.description && (
            <p className="whitespace-pre-wrap">{task.description}</p>
          )}
        </div>
      )}

      {canEdit && onDelete && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            onDelete(task);
          }}
          className="absolute right-2 bottom-2 hidden h-5 w-5 items-center justify-center rounded text-neutral-500 hover:bg-neutral-700 hover:text-red-400 group-hover:flex"
          title="Delete task"
        >
          ✕
        </button>
      )}
    </div>
  );
}
