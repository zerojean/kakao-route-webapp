-- Separate from the existing validation app. No anonymous/client access.
create table if not exists public.kakao_route_history (
    id text primary key,
    job_name text not null,
    original_file_name text,
    result_file_name text not null,
    storage_path text not null unique,
    row_count integer not null default 0,
    success_count integer not null default 0,
    failure_count integer not null default 0,
    created_at timestamptz not null default now(),
    deleted_at timestamptz
);
alter table public.kakao_route_history enable row level security;
revoke all on public.kakao_route_history from anon, authenticated;
grant all on public.kakao_route_history to service_role;
create index if not exists kakao_route_history_created_idx
    on public.kakao_route_history(created_at desc);
insert into storage.buckets (id, name, public)
values ('kakao-route-results', 'kakao-route-results', false)
on conflict (id) do update set public = false;
