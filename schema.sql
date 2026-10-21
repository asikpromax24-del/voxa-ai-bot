-- ASIKERA database schema. Run this once in Supabase: SQL Editor -> New query -> Run.

-- Users and premium status
create table if not exists users (
  id                  bigserial primary key,
  telegram_id         bigint unique not null,
  username            text,
  is_premium          boolean not null default false,
  premium_expiry      timestamptz,
  daily_message_count int not null default 0,
  last_message_date   date,
  created_at          timestamptz not null default now()
);

-- Chat memory (the bot reads the last 10 rows per user + mode)
create table if not exists chats (
  id           bigserial primary key,
  telegram_id  bigint not null references users(telegram_id) on delete cascade,
  mode         text not null,
  role         text not null check (role in ('user', 'assistant')),
  content      text not null,
  timestamp    timestamptz not null default now()
);
create index if not exists chats_user_mode_idx on chats (telegram_id, mode, timestamp desc);

-- Premium payment requests awaiting admin review
create table if not exists payments (
  id              bigserial primary key,
  telegram_id     bigint not null references users(telegram_id) on delete cascade,
  username        text,
  amount          numeric not null,
  trx_id          text not null,
  screenshot_url  text,                 -- stores the Telegram file_id of the screenshot
  status          text not null default 'pending'
                  check (status in ('pending', 'approved', 'rejected')),
  created_at      timestamptz not null default now(),
  reviewed_at     timestamptz
);
create index if not exists payments_status_idx on payments (status, created_at);

-- Lock the tables. The bot uses the SERVICE ROLE key, which bypasses RLS.
alter table users    enable row level security;
alter table chats    enable row level security;
alter table payments enable row level security;
