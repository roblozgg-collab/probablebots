# gentra — Telegram game bot

Working Python/aiogram project based on the **confirmed feature list** from the prompt. It does **not** claim to be an exact clone of GRAM where the original mechanics were unknown. Those unknown mechanics are implemented as documented **gentra rules** and their numeric values are configurable.

## Stack

- Python 3.10+
- aiogram 3.31.0
- SQLite (WAL + `BEGIN IMMEDIATE` for balance writes)
- Telegram Stars (`XTR`) for digital purchases
- pytest for core economy/game/payment/recovery tests

The bot token is read only from `.env`.

## Quick start — Windows

```powershell
cd gentra
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
python main.py
```

If PowerShell blocks activation, run once for the current shell:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

## Quick start — Linux/VPS

```bash
sudo mkdir -p /opt/gentra
sudo chown "$USER":"$USER" /opt/gentra
cd /opt/gentra
python3 -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
cp .env.example .env
nano .env
python main.py
```

For systemd, edit the user/path in `deploy/gentra.service`, then:

```bash
sudo cp deploy/gentra.service /etc/systemd/system/gentra.service
sudo systemctl daemon-reload
sudo systemctl enable --now gentra
sudo journalctl -u gentra -f
```

## BotFather setup for groups

Because roulette, transfers, treasury and duel calls use ordinary group messages (not only slash commands), the bot must be able to read those messages.

1. Open `@BotFather` → `/setprivacy` → select gentra → **Disable**.
2. Use `/setcommands` and add at least:

```text
start - open gentra
profile - profile
balance - balance
history - operation and duel history
top - balance leaderboard
duel - find a duel opponent
clans - clan menu
tournaments - tournaments
lang - language ru/uk/en
help - help
rules - rules
support_payments - payment support
```

3. Add the bot to a group and give it permission to send/edit its own messages. Administrator status is only required if your group policy requires it; changing the group language and group invite reward is checked against Telegram administrator status of the **user issuing the command**.

## Confirmed functions implemented

### Main menu

Buttons: Profile, Hogwarts, Commands, Donate, Tournaments, Chats, Clans, Games, Bonus, Policy and language selection.

### Admin panel

Set one or more owner Telegram IDs in `.env`:

```text
ADMIN_IDS=123456789,987654321
```

Owners get an `⚙️ Админ-панель` button in private chat after `/start`; `/admin` also opens the panel. The panel uses compact Telegram inline buttons and contains:

- `📢 РАССЫЛКА` — copy one text/media message to all registered non-blocked users, with preview, confirmation and delivery statistics;
- `👥 ПОЛЬЗОВАТЕЛИ` — find by Telegram ID, view profile, set exact GENTRA/galleon balances, edit all seven stats and toggle access blocking;
- `ℹ️ ИНФОРМАЦИЯ` — change the news, general-chat and roulette-chat links stored in SQLite; the `💬 Чаты` section reads these values immediately;
- `🚫 ЗАБЛОКИРОВАТЬ` — block or unblock a registered user. Blocked users cannot use messages, commands or callback buttons in private chats or groups. Pre-checkout is rejected for blocked users, while an already completed `successful_payment` event is still processed so a paid order cannot be lost.

Admin balance changes are written through the same economy operation ledger as normal balance changes. Broadcast runs are stored in SQLite.

### Profile/economy

Profile contains Telegram ID, GENTRA, galleons, total stats and clan. Defaults are configurable and currently set to the values from the prompt: `1000 GENTRA`, `2000 galleons`, all seven stats = `1`.

Commands and text aliases:

- `б`, `баланс`, `b`, `balance`, `/balance`
- reply `п 100` / `p 100`
- `п ID 100` / `p ID 100`
- `/профиль`, `профиль`, `/profile`, `profile`
- `/история`, `история`, `/history`, `history`
- `/дуэль`, `дуэль`, `/duel`, `duel`
- `/top N`, `top N`, `/топ N`, `топ N`, max 50
- `/lang ru|uk|en` and `lang ru|uk|en`; group changes require a Telegram administrator
- `казна`, `казна N`, `treasury`, `treasury N`
- `награда N`, `reward N`; configured range 1,000–2,000 GENTRA and group admin only

Transfers use one SQLite write transaction. Self-transfer, non-positive amount and overdraft are rejected. Each debit/credit uses unique event keys so the same Telegram event cannot debit twice.

### Stats / Hogwarts

Seven stats: block, endurance, health, intuition, strength, speed, charisma.

**gentra rule (not confirmed GRAM behavior):** next +1 cost:

```text
ceil(STAT_BASE_COST * current_level ^ STAT_GROWTH)
```

Defaults: base 10 galleons, growth 1.35. The observed level-1 price therefore remains 10 galleons.

### Roulette

Accepted target formats:

- `100 red` / `100 красное`
- `100 black` / `100 черное`
- `100 0` or any exact number 0–36
- `100 1-12`
- `100 odd`
- `100 even`
- round commands: `bets/ставки`, `cancel/отменить`, `double/удвоить`, `repeat/повторить`
- result log: `лог` / `log` / `/log` shows the latest settled roulette numbers for the current chat only
- `го` / `go` closes the current round immediately and settles it without waiting for the timer

**gentra rules for unknown original settings:**

The roulette log keeps using settled rounds already stored in SQLite, so it survives restarts. Default display size is 10 and can be changed with `ROULETTE_LOG_LIMIT` (1–50).

- the first bet in a chat starts a **45-second** round;
- rounds are isolated by chat ID and stored in SQLite;
- European wheel 0–36; zero is green and loses color/parity bets;
- exact number: total payout `x36`;
- red/black/odd/even: total payout `x2`;
- custom range of `N` numbers: `max(1.01, round((37/N)*0.97, 2))` total payout;
- `Cancel` refunds active bets while the round is still open;
- `Double` doubles all active bets and atomically debits the extra amount;
- `Repeat` reproduces the player's last settled bet set in that chat.

The result is generated with `secrets.SystemRandom`. Settlement moves the round to settled state and each bet payout has a unique operation key. On restart, overdue rounds are detected and settled once.

### Mines

Command: `мины 100`, `міни 100`, `mines 100`.

**gentra rule:** default 5×5 board, 5 mines. After `k` safe cells, payout multiplier is the inverse probability of surviving `k` openings multiplied by `MINES_HOUSE_FACTOR` (default 0.96), rounded to 2 decimals. Cashout is available after at least one safe cell. Board, mine positions, opened cells and state persist in SQLite. Only the creator's Telegram ID can use its callbacks.

### Joker

Command: `джокер 100` / `joker 100`.

**gentra rule:** 3 hidden cards, one Joker. Chance of winning = 1/3. Default total payout = `x2.85`. Game state is stored and can settle only once. Foreign callback users are rejected.

### Duels

- `/duel` in a group selects a recent participant from that chat;
- reply `дуэль` / `duel` or reply `/duel` challenges that user;
- opponent must explicitly accept;
- duel history is included in `/history`.

**gentra rule:** combat score = sum of seven stats + a uniform random value from `0..sum(stats)`. Default system reward is 250 GENTRA, cooldown 300 seconds. Self-duel is rejected.

### Clans

Implemented:

- create (`/clan_create Name`);
- invitations (`/clan_invite` as reply + accept/decline callback);
- open clan card and explicit Join confirmation;
- invitations list;
- clan list with pagination;
- search (`/clan_search text`);
- top clans;
- leave (`/clan_leave`);
- appoint deputy (`/clan_deputy` as reply);
- kick member (`/clan_kick` as reply);
- treasury deposit (`/clan_treasury 1000`).

Roles: owner and deputy may invite/kick ordinary members; only owner can appoint deputy. If owner leaves and a deputy exists, the deputy becomes owner. If there is no deputy, the clan is dissolved. Default creation price 50,000 GENTRA and member limit 50 are configurable.

### Player tournament

Confirmed rules from the prompt are implemented:

- daily roulette tournament;
- day boundary: 00:00 `Europe/Kyiv`;
- automatic participation, no entry fee;
- score = roulette payouts − roulette stakes;
- top 10;
- current player score and previous day view;
- prizes: `1,000,000; 500,000; 300,000; 200,000; 100,000; 75,000; 50,000; 30,000; 20,000; 10,000 GENTRA`.

Finalization is protected by `(day,type)` uniqueness plus unique award operation keys. On startup, the scheduler finalizes every past day that has score rows but no finalization record.

### Chat tournament — gentra-specific rule

The original rules were unknown, so this is intentionally separate:

- daily score = total roulette turnover in that group;
- top 3 groups;
- default prizes `250,000 / 150,000 / 100,000 GENTRA`;
- rewards go to the group's treasury, not a personal balance;
- same once-only finalization mechanism as the player tournament.

### Group treasury

- `казна` / `treasury` — create/show treasury;
- `казна 5000` / `treasury 5000` — player deposits GENTRA;
- `награда 1500` / `reward 1500` — administrators configure invite reward;
- allowed reward range: 1,000–2,000 GENTRA.

For `new_chat_members`, the service treats Telegram's message sender as inviter when that sender differs from the joined user. A `(chat_id,new_user_id)` primary key prevents paying the same new participant again after leave/rejoin. If Telegram reports a self-join (e.g. many invite-link joins), no inviter reward is guessed.

### Bonus

The `🎁 Bonus` menu button and `/bonus` command claim the bonus immediately without CAPTCHA or a verification code.

**gentra rule:** default bonus is 5,000 GENTRA once per 24h. The amount and period are configurable. The claim is executed in one SQLite write transaction and recorded with a unique event key, so the same Telegram event cannot credit twice. VIP uses the separately configurable shorter bonus period.

### Telegram Stars and VIP

Configured packages:

- 50 Stars → 100,000 GENTRA
- 100 → 204,000
- 250 → 525,000
- 500 → 1,150,000
- 1,000 → 2,300,000
- 2,500 → 6,250,000
- VIP → 100 Stars

Invoices use currency `XTR`. The bot validates user, currency, amount and stored payload in `pre_checkout_query`, but **delivers nothing there**. GENTRA/VIP is delivered only after `successful_payment`. `telegram_payment_charge_id` is unique in SQLite, preventing a second credit for the same payment.

`/support_payments` displays the configured support contact and the player's Telegram ID.

**gentra VIP rule (not confirmed from GRAM):** default 30 days, profile badge, and bonus cooldown reduced from 24h to 20h. VIP does not alter roulette/mines/joker probabilities or payouts.

### Languages

Russian, Ukrainian and English are included. `/lang ru`, `/lang uk`, `/lang en` work in private chat. In a group, only a Telegram administrator can change the group language. Main UI and game/system messages use the selected language. Common Latin aliases are supported.

### Data/security/recovery

- SQLite stores users, balances, operation ledger, roulette rounds/bets, mines, Joker, duels, clans, tournaments, group treasury, bonus claims and payments.
- balance changes are serialized with `BEGIN IMMEDIATE` and checked against negative balances;
- unique event/charge IDs make critical credits/debits idempotent;
- callback ownership/state is validated for player-owned games;
- randomness uses `secrets.SystemRandom`;
- logs do not print `.env` or bot token;
- roulette/tournament recovery runs on startup;
- unfinished inline games remain in SQLite and their existing Telegram buttons continue to reference the stored game IDs after a restart.

## Tests

```bash
pytest -q
```

The test suite covers:

- atomic transfer and duplicate-event protection;
- roulette payout rules;
- Stars order validation + idempotent settlement;
- clan role permissions;
- recovery/idempotent roulette settlement;
- once-only tournament awards;
- direct bonus claim, cooldown and duplicate-event protection;
- group treasury re-entry protection and insufficient-funds guard;
- admin settings persistence, blocking, balance journaling and stat editing.

## Important limitations

- This package was generated without your real `BOT_TOKEN`, so it has **not been launched against Telegram**.
- Telegram group invite attribution is limited by what Bot API service messages expose; invite-link joins often cannot be attributed to another inviter safely, and gentra intentionally does not guess.
- SQLite is appropriate for a local/single-process bot. For very large traffic or multiple bot workers, migrate the repository layer to PostgreSQL and use a distributed lock/job queue.
- The project does not provide cash withdrawal or conversion of GENTRA/galleons into money or cryptocurrency.

## Blackjack and dice

Player-facing references use `@username` when it is available. If a Telegram account has no username, gentra shows the saved first name instead of exposing the numeric Telegram ID. Transfers also accept `п @username сумма` / `p @username amount` in addition to reply transfers and numeric IDs.

Blackjack commands do not require punctuation: `бд 100`, `блекджек 100`, `bj 100`, `blackjack 100`. After the initial deal the bot shows inline buttons for Hit and Stand. Only the player who created the game can use them. The dealer keeps one card hidden until settlement and draws to the configured dealer stand value after the player stands or reaches 21. Default total payouts are x1 on a push, x1.5 on a normal win and x2 on a natural blackjack. Active state and the remaining deck are stored in SQLite so callbacks keep working after a restart.

Dice uses Telegram's native animated 🎲. `кб 100` / `kb 100` bets on 4–6, while `км 100` / `km 100` bets on 1–3. `куб больше 100`, `куб меньше 100`, `dice high 100` and `dice low 100` are also accepted. The bet is debited before the roll and the result is settled once after the Telegram dice value is returned. The default total win payout is x2.
