-- Run this once in Supabase SQL editor (Project -> SQL Editor -> New query)

create table if not exists goals (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  description text,
  target_date date,
  position int not null default 0,
  archived boolean not null default false,
  created_at timestamptz not null default now()
);

create table if not exists tasks (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  description text,
  status text not null default 'todo' check (status in ('todo', 'doing', 'done')),
  category text not null default 'board' check (category in ('board', 'longterm')),
  due_date date,
  due_time time,
  position int not null default 0,
  created_at timestamptz not null default now(),

  -- Tier 1 "define your task" fields. Nullable in the database so existing
  -- rows survive the migration; the app requires them on every create/edit,
  -- which is what retrofits the old tasks.
  goal_id uuid references goals(id) on delete set null,
  outcome text,
  effort text check (effort in ('15m', '30m', '1h', '2h', 'half_day', 'day_plus')),
  next_action text
);

-- Already ran this file before? Just add the new columns:
alter table tasks add column if not exists due_time time;
alter table tasks add column if not exists category text not null default 'board'
  check (category in ('board', 'longterm'));
alter table tasks add column if not exists goal_id uuid references goals(id) on delete set null;
alter table tasks add column if not exists outcome text;
alter table tasks add column if not exists effort text
  check (effort in ('15m', '30m', '1h', '2h', 'half_day', 'day_plus'));
alter table tasks add column if not exists next_action text;

create index if not exists tasks_goal_id_idx on tasks (goal_id);

alter table tasks enable row level security;
alter table goals enable row level security;

-- Open read/write policies: anyone with the anon key can read/write.
-- Editing in the app is gated by a client-side PIN, not by the database.
-- Good enough for a small personal/shared board; do not put sensitive data in it.
drop policy if exists "public read" on tasks;
drop policy if exists "public write" on tasks;
drop policy if exists "public update" on tasks;
drop policy if exists "public delete" on tasks;
create policy "public read" on tasks for select using (true);
create policy "public write" on tasks for insert with check (true);
create policy "public update" on tasks for update using (true);
create policy "public delete" on tasks for delete using (true);

drop policy if exists "public read" on goals;
drop policy if exists "public write" on goals;
drop policy if exists "public update" on goals;
drop policy if exists "public delete" on goals;
create policy "public read" on goals for select using (true);
create policy "public write" on goals for insert with check (true);
create policy "public update" on goals for update using (true);
create policy "public delete" on goals for delete using (true);

-- Enable realtime updates.
-- ALTER PUBLICATION has no IF NOT EXISTS, and re-adding a table raises 42710,
-- so check membership first to keep this file re-runnable.
do $$
begin
  if not exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'tasks'
  ) then
    alter publication supabase_realtime add table tasks;
  end if;

  if not exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'goals'
  ) then
    alter publication supabase_realtime add table goals;
  end if;
end $$;
