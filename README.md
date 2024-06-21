# Random peer mentor secret code

Use discord bot for random secret or message code for peer mentee (freshy) (first year stuent) to find peer mentor.

This code is designed for CS/CS UBRU.

## How it work

This code is a discord bot for user to use app commands (slash commands) and pops up a modal ui asking for user information including student ID, first name, and last name matching in mentee.csv, and when to check given.csv. If it does not exist it will be randomly drawn from mentor.csv. If it does exist it will be display. And when the user receives code or message, rpmsc sends the data to Google Sheets for easy viewing on other devices.

## Data

- `mentee.csv` peer mentee list [student id (integer), student full name (string)]
- `mentor.csv` peer mentor list [stduent id (integer), student full name (string), secret code or message (string)]
- `state.txt` (auto) save state of random list
- `given.csv` (auto) random log
- `rpmsc.log` (auto) logging file

## Setup

```sh
python3 -m venv venv
source ./venv/bin/activate

pip install -r ./requirements.txt
```

## Run

```sh
python ./rpmsc-bot.py
```

## .env file

```txt
DISCORD_RPMSC_TOKEN=
LISTEN_GUILD_ID=
SHEET_API_URL=https://script.google.com/...?token=...
START=YYYY-MM-DDThh:mm:ss.000000+00:00
END=YYYY-MM-DDThh:mm:ss.000000+00:00
```
