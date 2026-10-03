# Serverless API Tracker Bot

A serverless Telegram bot that tracks LeetCode activity for registered users and posts a daily leaderboard to group chats.

The project is designed to explore event-driven backend architecture using webhooks, SQL databases, scheduled jobs, and serverless cloud functions.

## Features

- Register LeetCode usernames through Telegram
- Store user data in a relational database
- Fetch daily statistics from the LeetCode GraphQL API
- Calculate daily score changes
- Generate and send leaderboards automatically
- Deploy without managing servers

## Stack

- Python
- Telegram Bot API
- LeetCode GraphQL API
- SQLite / PostgreSQL
- SQLAlchemy
- AWS Lambda / Cloudflare Workers / Google Cloud Functions

## Architecture

```
Telegram User
      │
      ▼
Telegram Webhook
      │
      ▼
Serverless Function
      │
      ▼
 SQL Database
      ▲
      │
Scheduled Cron Job
      │
      ▼
LeetCode API
      │
      ▼
Leaderboard
      │
      ▼
Telegram Group
```

## Workflow

### Registration

```
/register <leetcode_username>
```

The bot stores the Telegram chat ID and the associated LeetCode username.

### Daily Update

A scheduled cloud function runs every day.

For each registered user it:

1. Fetches current LeetCode statistics.
2. Compares them with the previous day's snapshot.
3. Computes the daily score.
4. Updates the database.
5. Posts the leaderboard to Telegram.

## Database

### Users

| Field | Description |
|-------|-------------|
| id | Internal user ID |
| telegram_chat_id | Telegram chat |
| leetcode_handle | Username |
| total_score | Cumulative score |

### DailyStats

| Field | Description |
|-------|-------------|
| user_id | Reference to Users |
| date | Snapshot date |
| easy | Easy problems solved |
| medium | Medium problems solved |
| hard | Hard problems solved |
| daily_score | Points earned that day |

## Roadmap

- [ ] Telegram registration
- [ ] LeetCode API integration
- [ ] Database schema
- [ ] Daily scoring logic
- [ ] Leaderboard generation
- [ ] Serverless deployment
- [ ] Scheduled execution
- [ ] Multi-platform support (Codeforces, AtCoder)

## Concepts Explored

- Webhooks
- Serverless computing
- REST & GraphQL APIs
- Relational databases
- Scheduled jobs
- Event-driven architecture

## Results API

`GET /api/v1/weights` returns portfolio-weight results. By default it returns
all matching records, sorted by newest date first. The response contains the
results, the total number of matches, pagination details, and the parameters
used for the query.

Supported query parameters:

| Parameter | Type | Description |
|-----------|------|-------------|
| `ticker` | string | Filter by ticker symbol |
| `signal` | string | Filter by signal (`BUY`, `SELL`, or `HOLD`) |
| `start_date` | ISO-8601 datetime | Include records on or after this timestamp |
| `end_date` | ISO-8601 datetime | Include records on or before this timestamp |
| `sort_by` | `id`, `date`, `ticker`, `weight`, `signal` | Result field to sort by |
| `sort_order` | `asc`, `desc` | Sort direction |
| `offset` | integer | Number of matching records to skip (default `0`) |
| `limit` | integer | Maximum records to return, from `1` to `1000`; omit for all matches |

Example:

```text
/api/v1/weights?ticker=BTC-USD&sort_by=weight&sort_order=desc&limit=25
```

Interactive OpenAPI documentation is available at `/docs` when the API is
running.
