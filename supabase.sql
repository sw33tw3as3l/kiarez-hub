-- Run this once in Supabase SQL editor (Project -> SQL Editor -> New query)

create table if not exists tasks (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  description text,
  status text not null default 'todo' check (status in ('todo', 'doing', 'done')),
  due_date date,
  position int not null default 0,
  created_at timestamptz not null default now()
);

alter table tasks enable row level security;

-- Open read/write policies: anyone with the anon key can read/write.
-- Editing in the app is gated by a client-side PIN, not by the database.
-- Good enough for a small personal/shared board; do not put sensitive data in it.
create policy "public read" on tasks for select using (true);
create policy "public write" on tasks for insert with check (true);
create policy "public update" on tasks for update using (true);
create policy "public delete" on tasks for delete using (true);

-- Enable realtime updates
alter publication supabase_realtime add table tasks;
