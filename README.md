# Telegram Mining App

This is a Telegram bot for a mining app where users can mine $MEGA tokens, earn rewards through referrals, and complete tasks to earn additional tokens. The bot also includes an energy system and admin functionalities.

## Features

- Mining $MEGA tokens with daily limits
- Referral system with rewards
- Achievements and streak bonuses
- Admin commands for managing users and settings
- Task system for users to complete tasks and earn rewards
- Energy plans to increase daily mining limits
- Leaderboard to view top miners

## Setup

### Prerequisites

- Python 3.8+
- Telegram Bot Token (create a bot using [BotFather](https://core.telegram.org/bots#botfather))
- Telegram user ID for admin (get your user ID from [userinfobot](https://t.me/userinfobot))

### Installation

1. Clone the repository:
    ```sh
    git clone https://github.com/yourusername/telegram-mining-app.git
    cd telegram-mining-app
    ```

2. Create a virtual environment and activate it:
    ```sh
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    ```

3. Install the required packages:
    ```sh
    pip install -r requirements.txt
    ```

4. Create a `.env` file in the project directory and add your bot token and other configurations:
    ```properties
    BOT_TOKEN=your-telegram-bot-token
    MINING_REWARD=100
    REFERRAL_REWARD=50
    ADMIN_IDS=your-telegram-user-id
    SUSPICIOUS_THRESHOLD=5
    ```

### Running the Bot

1. Start the bot:
    ```sh
    python bot.py
    ```

2. The bot should now be running and you can interact with it on Telegram.

## Usage

### User Commands

- `/start` - Start the bot and get a referral link
- `/mine` - Mine $MEGA tokens
- `/balance` - Check your balance
- `/stats` - View your mining statistics
- `/referral` - Get your referral link
- `/achievements` - View your achievements
- `/profile` - View your detailed profile
- `/leaderboard` - View top miners
- `/tasks` - View available tasks
- `/energy_shop` - View and purchase energy plans
- `/energy_status` - Check your current energy plan status

### Admin Commands

- `/admin_stats` - View admin statistics
- `/monitor <user_id>` - Monitor specific user activity
- `/suspend <user_id>` - Suspend a user
- `/unsuspend <user_id>` - Unsuspend a user
- `/config_get` - View current bot configuration
- `/config_set <param> <value>` - Change bot settings
- `/announce <message>` - Send announcement to all users
- `/broadcast <target> <message>` - Send targeted announcement
- `/add_admin <user_id> <role>` - Add a new admin or moderator
- `/remove_admin <user_id>` - Remove an admin or moderator
- `/add_task "title" "description" "link" "display_text" reward` - Add a new task
- `/remove_task <task_id>` - Remove a task
- `/task_stats` - View task statistics

## License

This project is licensed under the MIT License.
